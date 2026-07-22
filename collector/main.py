#!/usr/bin/env python3
"""Collect Raspberry Pi host metrics with Linux system tools and push them to Pushgateway."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable


DEFAULT_PUSHGATEWAY = "http://127.0.0.1:9091"
DEFAULT_JOB_NAME = "raspberry_pi_macro_metrics"
DEFAULT_INTERVAL_SECONDS = 5
TOOL_SAMPLE_SECONDS = 1
REQUIRED_COMMANDS = ("mpstat", "vmstat", "sar", "iostat")
PID_REQUIRED_COMMANDS = ("pidstat",)
PID_DISCOVERY_REQUIRED_COMMANDS = ("ss",)
COMMAND_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}
PID_PATTERN = re.compile(r"pid=(\d+)")
PID_IO_FIELDS = ("rchar", "wchar", "read_bytes", "write_bytes")


@dataclass
class ProcessIOSnapshot:
	pid: int
	counters: Dict[str, int]


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Push Raspberry Pi CPU, memory, network, and disk metrics to a Prometheus Pushgateway."
	)
	parser.add_argument(
		"--pushgateway",
		default=DEFAULT_PUSHGATEWAY,
		help=f"Pushgateway base URL. Default: {DEFAULT_PUSHGATEWAY}",
	)
	parser.add_argument(
		"--job",
		default=DEFAULT_JOB_NAME,
		help=f"Prometheus job name used when pushing metrics. Default: {DEFAULT_JOB_NAME}",
	)
	parser.add_argument(
		"--interval",
		type=int,
		default=DEFAULT_INTERVAL_SECONDS,
		help=f"Seconds between samples. Default: {DEFAULT_INTERVAL_SECONDS}",
	)
	pid_group = parser.add_mutually_exclusive_group()
	pid_group.add_argument(
		"--pid",
		type=int,
		help="Collect app-scoped CPU, memory, and disk I/O for this PID instead of host-wide metrics.",
	)
	pid_group.add_argument(
		"--pid-file",
		help="Read the target PID from this file before each sample. Useful if the app PID changes on restart.",
	)
	pid_group.add_argument(
		"--discover-port",
		type=int,
		help="Auto-discover the target PID from the process listening on this TCP port.",
	)
	return parser.parse_args()


def pid_mode_enabled(args: argparse.Namespace) -> bool:
	return args.pid is not None or args.pid_file is not None or args.discover_port is not None


def ensure_required_commands(args: argparse.Namespace) -> None:
	missing = [command for command in REQUIRED_COMMANDS if shutil.which(command) is None]
	if pid_mode_enabled(args):
		missing.extend(command for command in PID_REQUIRED_COMMANDS if shutil.which(command) is None)
	if args.discover_port is not None:
		missing.extend(command for command in PID_DISCOVERY_REQUIRED_COMMANDS if shutil.which(command) is None)
	if missing:
		raise RuntimeError(
			"missing required Linux commands: "
			+ ", ".join(missing)
			+ ". Install procps, iproute2, and sysstat before starting the collector."
		)


def run_command(command: list[str]) -> str:
	try:
		result = subprocess.run(
			command,
			check=True,
			capture_output=True,
			text=True,
			env=COMMAND_ENV,
		)
	except subprocess.CalledProcessError as exc:
		stderr = exc.stderr.strip() or exc.stdout.strip()
		raise RuntimeError(f"{command[0]} failed: {stderr}") from exc

	return result.stdout


def read_cpu_info() -> Dict[str, str]:
	info: Dict[str, str] = {}

	with open("/proc/cpuinfo", "r", encoding="utf-8") as cpu_info:
		for raw_line in cpu_info:
			line = raw_line.strip()
			if not line or ":" not in line:
				continue

			key, value = [part.strip() for part in line.split(":", 1)]
			if key in {"Model", "Hardware", "Revision", "Serial"}:
				info[key.lower()] = value

	return info


def parse_listening_pids_output(output: str) -> list[int]:
	return sorted({int(match.group(1)) for match in PID_PATTERN.finditer(output)})


def discover_pid_for_port(port: int) -> int:
	output = run_command(["ss", "-ltnpH", f"sport = :{port}"])
	pids = parse_listening_pids_output(output)
	if not pids:
		raise RuntimeError(f"failed to auto-discover pid for port {port}: no listening process found")
	if len(pids) > 1:
		pid_list = ", ".join(str(pid) for pid in pids)
		raise RuntimeError(
			f"failed to auto-discover pid for port {port}: multiple listening processes found ({pid_list})"
		)
	return pids[0]


def resolve_pid(args: argparse.Namespace) -> int | None:
	if args.pid is not None:
		return args.pid
	if args.pid_file:
		try:
			raw_pid = open(args.pid_file, "r", encoding="utf-8").read().strip()
		except OSError as exc:
			raise RuntimeError(f"failed to read pid file {args.pid_file}: {exc}") from exc

		if not raw_pid.isdigit():
			raise RuntimeError(f"pid file {args.pid_file} did not contain a valid integer PID")

		return int(raw_pid)
	if args.discover_port is not None:
		return discover_pid_for_port(args.discover_port)
	return None


def parse_tabular_average_output(output: str, entity_field: str) -> tuple[list[str], list[list[str]]]:
	headers: list[str] | None = None
	rows: list[list[str]] = []

	for line in output.splitlines():
		parts = line.split()
		if not parts:
			continue

		if entity_field in parts:
			start_index = parts.index(entity_field)
			headers = parts[start_index:]
			continue

		if parts[0] != "Average:" or headers is None:
			continue

		row = parts[-len(headers) :]
		if row[0] == entity_field:
			continue
		rows.append(row)

	if headers is None:
		raise RuntimeError(f"failed to parse {entity_field} output")

	return headers, rows


def parse_pidstat_average_output(output: str, command_name: str) -> tuple[list[str], list[list[str]]]:
	headers: list[str] | None = None
	rows: list[list[str]] = []

	for line in output.splitlines():
		parts = line.split()
		if not parts:
			continue

		if command_name in parts and "PID" in parts:
			start_index = parts.index("UID")
			headers = parts[start_index:]
			continue

		if parts[0] != "Average:" or headers is None:
			continue

		row = parts[-len(headers) :]
		if row[0] == "UID":
			continue
		rows.append(row)

	if headers is None:
		raise RuntimeError(f"failed to parse {command_name} output")

	return headers, rows


def parse_pid_io_output(output: str) -> Dict[str, int]:
	counters: Dict[str, int] = {}

	for line in output.splitlines():
		if ":" not in line:
			continue
		key, raw_value = [part.strip() for part in line.split(":", 1)]
		if key not in PID_IO_FIELDS:
			continue
		if not raw_value.isdigit():
			raise RuntimeError(f"invalid integer value for {key} in /proc pid io output")
		counters[key] = int(raw_value)

	missing = [field for field in PID_IO_FIELDS if field not in counters]
	if missing:
		raise RuntimeError(f"missing expected /proc pid io fields: {', '.join(missing)}")

	return counters


def read_pid_io_snapshot(pid: int) -> ProcessIOSnapshot:
	path = f"/proc/{pid}/io"
	try:
		with open(path, "r", encoding="utf-8") as io_file:
			output = io_file.read()
	except OSError as exc:
		raise RuntimeError(f"failed to read {path}: {exc}") from exc

	return ProcessIOSnapshot(pid=pid, counters=parse_pid_io_output(output))


def parse_cpu_metrics_output(output: str) -> list[str]:
	headers, rows = parse_tabular_average_output(output, "CPU")
	idle_index = headers.index("%idle")
	lines = ["# TYPE raspberry_pi_cpu_usage_percent gauge"]

	for row in rows:
		cpu_name = row[0]
		label = "cpu" if cpu_name == "all" else f"cpu{cpu_name}"
		busy_percent = max(0.0, 100.0 - float(row[idle_index]))
		lines.append(f'raspberry_pi_cpu_usage_percent{{cpu="{label}"}} {busy_percent:.2f}')

	return lines


def parse_cpu_metrics() -> list[str]:
	return parse_cpu_metrics_output(run_command(["mpstat", "-P", "ALL", str(TOOL_SAMPLE_SECONDS), "1"]))


def parse_memory_metrics_output(output: str) -> list[str]:
	values: Dict[str, int] = {}

	for line in output.splitlines():
		parts = line.split(None, 1)
		if len(parts) != 2 or not parts[0].isdigit():
			continue
		label = parts[1].strip()
		if label.startswith("K "):
			label = label[2:]
		values[label] = int(parts[0]) * 1024

	mem_total = values.get("total memory", 0)
	mem_used = values.get("used memory", 0)
	mem_free = values.get("free memory", 0)
	mem_available = mem_free
	mem_used_percent = (mem_used / mem_total * 100.0) if mem_total else 0.0

	return [
		"# TYPE raspberry_pi_memory_total_bytes gauge",
		"# TYPE raspberry_pi_memory_available_bytes gauge",
		"# TYPE raspberry_pi_memory_free_bytes gauge",
		"# TYPE raspberry_pi_memory_used_bytes gauge",
		"# TYPE raspberry_pi_memory_used_percent gauge",
		f"raspberry_pi_memory_total_bytes {mem_total}",
		f"raspberry_pi_memory_available_bytes {mem_available}",
		f"raspberry_pi_memory_free_bytes {mem_free}",
		f"raspberry_pi_memory_used_bytes {mem_used}",
		f"raspberry_pi_memory_used_percent {mem_used_percent:.2f}",
	]


def parse_memory_metrics() -> list[str]:
	return parse_memory_metrics_output(run_command(["vmstat", "-s", "-S", "K"]))


def parse_network_metrics_output(output: str) -> list[str]:
	headers, rows = parse_tabular_average_output(output, "IFACE")
	rx_index = headers.index("rxkB/s")
	tx_index = headers.index("txkB/s")
	lines = [
		"# TYPE raspberry_pi_network_receive_bytes_per_second gauge",
		"# TYPE raspberry_pi_network_transmit_bytes_per_second gauge",
	]

	for row in rows:
		iface = row[0]
		if iface == "lo":
			continue
		rx_bytes_per_second = float(row[rx_index]) * 1024
		tx_bytes_per_second = float(row[tx_index]) * 1024
		lines.append(
			f'raspberry_pi_network_receive_bytes_per_second{{iface="{iface}"}} {rx_bytes_per_second:.2f}'
		)
		lines.append(
			f'raspberry_pi_network_transmit_bytes_per_second{{iface="{iface}"}} {tx_bytes_per_second:.2f}'
		)

	return lines


def parse_network_metrics() -> list[str]:
	return parse_network_metrics_output(run_command(["sar", "-n", "DEV", str(TOOL_SAMPLE_SECONDS), "1"]))


def parse_disk_metrics_output(output: str) -> list[str]:
	headers: list[str] | None = None
	rows: list[list[str]] = []

	for line in output.splitlines():
		parts = line.split()
		if not parts:
			continue

		if parts[0] == "Device":
			headers = parts
			rows = []
			continue

		if headers is None or parts[0].startswith("Linux"):
			continue

		if len(parts) >= len(headers):
			rows.append(parts[: len(headers)])

	if headers is None:
		raise RuntimeError("failed to parse iostat output")

	read_index = headers.index("kB_read/s")
	write_index = headers.index("kB_wrtn/s")
	lines = [
		"# TYPE raspberry_pi_disk_read_bytes_per_second gauge",
		"# TYPE raspberry_pi_disk_write_bytes_per_second gauge",
	]

	for row in rows:
		device = row[0]
		read_bytes_per_second = float(row[read_index]) * 1024
		write_bytes_per_second = float(row[write_index]) * 1024
		lines.append(
			f'raspberry_pi_disk_read_bytes_per_second{{device="{device}"}} {read_bytes_per_second:.2f}'
		)
		lines.append(
			f'raspberry_pi_disk_write_bytes_per_second{{device="{device}"}} {write_bytes_per_second:.2f}'
		)

	return lines


def parse_disk_metrics() -> list[str]:
	return parse_disk_metrics_output(run_command(["iostat", "-d", "-k", str(TOOL_SAMPLE_SECONDS), "2"]))


def parse_pid_cpu_metrics_output(output: str, pid: int) -> list[str]:
	headers, rows = parse_pidstat_average_output(output, "Command")
	pid_index = headers.index("PID")
	cpu_index = headers.index("%CPU")
	command_index = headers.index("Command")
	lines = ["# TYPE raspberry_pi_app_cpu_usage_percent gauge"]

	for row in rows:
		if int(row[pid_index]) != pid:
			continue
		command = row[command_index]
		lines.append(
			f'raspberry_pi_app_cpu_usage_percent{{pid="{pid}",command="{command}"}} {float(row[cpu_index]):.2f}'
		)

	return lines


def parse_pid_cpu_metrics(pid: int) -> list[str]:
	return parse_pid_cpu_metrics_output(
		run_command(["pidstat", "-u", "-p", str(pid), str(TOOL_SAMPLE_SECONDS), "1"]),
		pid,
	)


def parse_pid_memory_metrics_output(output: str, pid: int) -> list[str]:
	headers, rows = parse_pidstat_average_output(output, "Command")
	pid_index = headers.index("PID")
	vsz_index = headers.index("VSZ")
	rss_index = headers.index("RSS")
	mem_index = headers.index("%MEM")
	command_index = headers.index("Command")
	lines = [
		"# TYPE raspberry_pi_app_memory_virtual_bytes gauge",
		"# TYPE raspberry_pi_app_memory_resident_bytes gauge",
		"# TYPE raspberry_pi_app_memory_percent gauge",
	]

	for row in rows:
		if int(row[pid_index]) != pid:
			continue
		command = row[command_index]
		lines.append(
			f'raspberry_pi_app_memory_virtual_bytes{{pid="{pid}",command="{command}"}} {int(row[vsz_index]) * 1024}'
		)
		lines.append(
			f'raspberry_pi_app_memory_resident_bytes{{pid="{pid}",command="{command}"}} {int(row[rss_index]) * 1024}'
		)
		lines.append(
			f'raspberry_pi_app_memory_percent{{pid="{pid}",command="{command}"}} {float(row[mem_index]):.2f}'
		)

	return lines


def parse_pid_memory_metrics(pid: int) -> list[str]:
	return parse_pid_memory_metrics_output(
		run_command(["pidstat", "-r", "-p", str(pid), str(TOOL_SAMPLE_SECONDS), "1"]),
		pid,
	)


def format_pid_io_metrics(
	pid: int,
	command: str,
	current_snapshot: ProcessIOSnapshot,
	previous_snapshot: ProcessIOSnapshot | None,
	interval_seconds: int,
) -> list[str]:
	lines = [
		"# TYPE raspberry_pi_app_io_read_chars_bytes_per_second gauge",
		"# TYPE raspberry_pi_app_io_write_chars_bytes_per_second gauge",
		"# TYPE raspberry_pi_app_disk_read_bytes_per_second gauge",
		"# TYPE raspberry_pi_app_disk_write_bytes_per_second gauge",
	]

	if previous_snapshot is None or previous_snapshot.pid != current_snapshot.pid:
		deltas = {field: 0 for field in PID_IO_FIELDS}
	else:
		deltas = {
			field: max(0, current_snapshot.counters[field] - previous_snapshot.counters[field])
			for field in PID_IO_FIELDS
		}

	read_chars_per_second = deltas["rchar"] / interval_seconds
	write_chars_per_second = deltas["wchar"] / interval_seconds
	read_bytes_per_second = deltas["read_bytes"] / interval_seconds
	write_bytes_per_second = deltas["write_bytes"] / interval_seconds

	lines.append(
		f'raspberry_pi_app_io_read_chars_bytes_per_second{{pid="{pid}",command="{command}"}} {read_chars_per_second:.2f}'
	)
	lines.append(
		f'raspberry_pi_app_io_write_chars_bytes_per_second{{pid="{pid}",command="{command}"}} {write_chars_per_second:.2f}'
	)
	lines.append(
		f'raspberry_pi_app_disk_read_bytes_per_second{{pid="{pid}",command="{command}"}} {read_bytes_per_second:.2f}'
	)
	lines.append(
		f'raspberry_pi_app_disk_write_bytes_per_second{{pid="{pid}",command="{command}"}} {write_bytes_per_second:.2f}'
	)

	return lines


def parse_pid_disk_metrics(
	pid: int,
	command: str,
	current_snapshot: ProcessIOSnapshot,
	previous_snapshot: ProcessIOSnapshot | None,
	interval_seconds: int,
) -> list[str]:
	return format_pid_io_metrics(pid, command, current_snapshot, previous_snapshot, interval_seconds)


def read_process_command(pid: int) -> str:
	path = f"/proc/{pid}/comm"
	try:
		with open(path, "r", encoding="utf-8") as comm_file:
			command = comm_file.read().strip()
	except OSError as exc:
		raise RuntimeError(f"failed to read {path}: {exc}") from exc

	return command or "unknown"


def format_pi_info(info: Dict[str, str]) -> Iterable[str]:
	if not info:
		return []

	labels = ",".join(
		f'{key}="{value.replace(chr(34), "")}"' for key, value in sorted(info.items())
	)
	return [
		"# TYPE raspberry_pi_info gauge",
		f"raspberry_pi_info{{{labels}}} 1",
	]


def format_pid_mode_info(pid: int) -> list[str]:
	return [
		"# TYPE raspberry_pi_app_scope_info gauge",
		f'raspberry_pi_app_scope_info{{pid="{pid}",scope="process",network_scope="unsupported"}} 1',
	]


def sample_metrics(
	pid: int | None = None,
	previous_io_snapshot: ProcessIOSnapshot | None = None,
	interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> tuple[str, ProcessIOSnapshot | None]:
	cpu_info = read_cpu_info()
	lines: list[str] = []
	next_io_snapshot: ProcessIOSnapshot | None = None
	if pid is None:
		lines.extend(parse_cpu_metrics())
		lines.extend(parse_memory_metrics())
		lines.extend(parse_network_metrics())
		lines.extend(parse_disk_metrics())
	else:
		next_io_snapshot = read_pid_io_snapshot(pid)
		command = read_process_command(pid)
		lines.extend(parse_pid_cpu_metrics(pid))
		lines.extend(parse_pid_memory_metrics(pid))
		lines.extend(parse_pid_disk_metrics(pid, command, next_io_snapshot, previous_io_snapshot, interval_seconds))
		lines.extend(format_pid_mode_info(pid))
	lines.extend(format_pi_info(cpu_info))
	return "\n".join(lines) + "\n", next_io_snapshot


def push_metrics(pushgateway_url: str, job_name: str, instance: str, payload: str) -> None:
	url = f"{pushgateway_url.rstrip('/')}/metrics/job/{job_name}/instance/{instance}"
	request = urllib.request.Request(
		url=url,
		data=payload.encode("utf-8"),
		method="PUT",
		headers={"Content-Type": "text/plain; version=0.0.4"},
	)

	with urllib.request.urlopen(request, timeout=10) as response:
		if response.status >= 300:
			raise RuntimeError(f"pushgateway returned unexpected status {response.status}")


def main() -> int:
	args = parse_args()
	pushgateway_url = args.pushgateway
	job_name = args.job
	interval = args.interval
	instance = socket.gethostname()

	if interval <= 0:
		print("interval must be positive", file=sys.stderr)
		return 1

	try:
		ensure_required_commands(args)
	except RuntimeError as exc:
		print(exc, file=sys.stderr)
		return 1

	previous_io_snapshot: ProcessIOSnapshot | None = None

	while True:
		start = time.monotonic()
		pid: int | None = None

		try:
			pid = resolve_pid(args)
			payload, previous_io_snapshot = sample_metrics(
				pid=pid,
				previous_io_snapshot=previous_io_snapshot,
				interval_seconds=interval,
			)
			push_metrics(pushgateway_url, job_name, instance, payload)
			print(
				f"pushed metrics to {pushgateway_url} at {time.strftime('%Y-%m-%d %H:%M:%S')}",
				flush=True,
			)
		except (OSError, RuntimeError, urllib.error.URLError) as exc:
			if pid is None:
				previous_io_snapshot = None
			print(f"failed to push metrics: {exc}", file=sys.stderr, flush=True)

		elapsed = time.monotonic() - start
		time.sleep(max(interval - elapsed, 0))


if __name__ == "__main__":
	raise SystemExit(main())
