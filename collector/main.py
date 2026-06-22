#!/usr/bin/env python3
"""Collect Raspberry Pi host metrics and push them to a Prometheus Pushgateway."""

from __future__ import annotations

import argparse
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict


DEFAULT_PUSHGATEWAY = "http://127.0.0.1:9091"
DEFAULT_JOB_NAME = "raspberry_pi_procfs"
DEFAULT_INTERVAL_SECONDS = 5


@dataclass
class CpuTimes:
	total: int
	idle: int


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Push Raspberry Pi CPU and memory metrics to a Prometheus Pushgateway."
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


def read_proc_stat() -> Dict[str, CpuTimes]:
	stats: Dict[str, CpuTimes] = {}

	with open("/proc/stat", "r", encoding="utf-8") as proc_stat:
		for line in proc_stat:
			parts = line.split()
			if not parts or not parts[0].startswith("cpu"):
				continue

			name = parts[0]
			values = [int(value) for value in parts[1:]]
			idle = values[3] + (values[4] if len(values) > 4 else 0)
			total = sum(values)
			stats[name] = CpuTimes(total=total, idle=idle)

	return stats


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


def read_meminfo() -> Dict[str, int]:
	meminfo: Dict[str, int] = {}

	with open("/proc/meminfo", "r", encoding="utf-8") as meminfo_file:
		for line in meminfo_file:
			parts = line.replace(":", "").split()
			if len(parts) < 2:
				continue
			meminfo[parts[0]] = int(parts[1]) * 1024

	return meminfo


def compute_cpu_busy_percent(previous: CpuTimes, current: CpuTimes) -> float:
	total_delta = current.total - previous.total
	idle_delta = current.idle - previous.idle

	if total_delta <= 0:
		return 0.0

	busy_delta = total_delta - idle_delta
	return (busy_delta / total_delta) * 100.0


def sample_metrics(previous_cpu: Dict[str, CpuTimes], current_cpu: Dict[str, CpuTimes]) -> str:
	meminfo = read_meminfo()
	cpu_info = read_cpu_info()
	mem_total = meminfo.get("MemTotal", 0)
	mem_available = meminfo.get("MemAvailable", 0)
	mem_used = max(mem_total - mem_available, 0)
	mem_used_percent = (mem_used / mem_total * 100.0) if mem_total else 0.0

	lines = [
		"# TYPE raspberry_pi_cpu_usage_percent gauge",
		"# TYPE raspberry_pi_memory_total_bytes gauge",
		"# TYPE raspberry_pi_memory_available_bytes gauge",
		"# TYPE raspberry_pi_memory_used_bytes gauge",
		"# TYPE raspberry_pi_memory_used_percent gauge",
	]

	for cpu_name in sorted(current_cpu):
		if cpu_name not in previous_cpu:
			continue
		busy_percent = compute_cpu_busy_percent(previous_cpu[cpu_name], current_cpu[cpu_name])
		lines.append(f'raspberry_pi_cpu_usage_percent{{cpu="{cpu_name}"}} {busy_percent:.2f}')

	lines.extend(
		[
			f"raspberry_pi_memory_total_bytes {mem_total}",
			f"raspberry_pi_memory_available_bytes {mem_available}",
			f"raspberry_pi_memory_used_bytes {mem_used}",
			f"raspberry_pi_memory_used_percent {mem_used_percent:.2f}",
		]
	)

	if cpu_info:
		lines.append("# TYPE raspberry_pi_info gauge")
		labels = ",".join(
			f'{key}="{value.replace(chr(34), "")}"' for key, value in sorted(cpu_info.items())
		)
		lines.append(f"raspberry_pi_info{{{labels}}} 1")

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

	previous_cpu = read_proc_stat()

	while True:
		time.sleep(interval)
		current_cpu = read_proc_stat()
		payload = sample_metrics(previous_cpu, current_cpu)

		try:
			push_metrics(pushgateway_url, job_name, instance, payload)
			print(f"pushed metrics to {pushgateway_url} at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
		except (OSError, urllib.error.URLError, RuntimeError) as exc:
			print(f"failed to push metrics: {exc}", file=sys.stderr, flush=True)

		previous_cpu = current_cpu


if __name__ == "__main__":
	raise SystemExit(main())
