#!/usr/bin/env python3
"""Collect Raspberry Pi host metrics with Linux system tools and push them to Pushgateway."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, Iterable


DEFAULT_PUSHGATEWAY = "http://127.0.0.1:9091"
DEFAULT_JOB_NAME = "raspberry_pi_macro_metrics"
DEFAULT_INTERVAL_SECONDS = 10
TOOL_SAMPLE_SECONDS = 1
REQUIRED_COMMANDS = ("mpstat", "vmstat", "sar", "iostat")
COMMAND_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


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
	return parser.parse_args()


def ensure_required_commands() -> None:
	missing = [command for command in REQUIRED_COMMANDS if shutil.which(command) is None]
	if missing:
		raise RuntimeError(
			"missing required Linux commands: "
			+ ", ".join(missing)
			+ ". Install procps and sysstat before starting the collector."
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


def sample_metrics() -> str:
	cpu_info = read_cpu_info()
	lines: list[str] = []
	lines.extend(parse_cpu_metrics())
	lines.extend(parse_memory_metrics())
	lines.extend(parse_network_metrics())
	lines.extend(parse_disk_metrics())
	lines.extend(format_pi_info(cpu_info))
	return "\n".join(lines) + "\n"


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
		ensure_required_commands()
	except RuntimeError as exc:
		print(exc, file=sys.stderr)
		return 1

	while True:
		start = time.monotonic()

		try:
			payload = sample_metrics()
			push_metrics(pushgateway_url, job_name, instance, payload)
			print(
				f"pushed metrics to {pushgateway_url} at {time.strftime('%Y-%m-%d %H:%M:%S')}",
				flush=True,
			)
		except (OSError, RuntimeError, urllib.error.URLError) as exc:
			print(f"failed to push metrics: {exc}", file=sys.stderr, flush=True)

		elapsed = time.monotonic() - start
		time.sleep(max(interval - elapsed, 0))


if __name__ == "__main__":
	raise SystemExit(main())
