#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${REPO_ROOT}/.pi-runtime"
BIN_DIR="${RUNTIME_DIR}/bin"
LOG_DIR="${RUNTIME_DIR}/logs"
PID_DIR="${RUNTIME_DIR}/pids"
PROMETHEUS_DATA_DIR="${PROMETHEUS_DATA_DIR:-${RUNTIME_DIR}/prometheus-data}"

SERVICE_PORT="${SERVICE_PORT:-8080}"
PUSHGATEWAY_PORT="${PUSHGATEWAY_PORT:-9091}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9092}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
COLLECTOR_INTERVAL="${COLLECTOR_INTERVAL:-5}"
PROMETHEUS_CONFIG="${PROMETHEUS_CONFIG:-${REPO_ROOT}/deploy/prometheus.yml}"
PUSHGATEWAY_URL="${PUSHGATEWAY_URL:-http://127.0.0.1:${PUSHGATEWAY_PORT}}"

mkdir -p "${BIN_DIR}" "${LOG_DIR}" "${PID_DIR}" "${PROMETHEUS_DATA_DIR}"

find_binary_dir() {
	local pattern="$1"
	find "${HOME}" -maxdepth 1 -type d -name "${pattern}" | sort | tail -n 1
}

require_command() {
	local command_name="$1"
	if ! command -v "${command_name}" >/dev/null 2>&1; then
		echo "missing required command: ${command_name}" >&2
		exit 1
	fi
}

ensure_port_free() {
	local port="$1"
	local label="$2"
	if ss -ltn "sport = :${port}" | grep -q ":${port}"; then
		echo "${label} port ${port} is already in use" >&2
		exit 1
	fi
}

pid_file_for() {
	local name="$1"
	echo "${PID_DIR}/${name}.pid"
}

log_file_for() {
	local name="$1"
	echo "${LOG_DIR}/${name}.log"
}

start_background() {
	local name="$1"
	shift

	local pid_file
	local log_file
	pid_file="$(pid_file_for "${name}")"
	log_file="$(log_file_for "${name}")"

	if [[ -f "${pid_file}" ]]; then
		local existing_pid
		existing_pid="$(cat "${pid_file}")"
		if kill -0 "${existing_pid}" >/dev/null 2>&1; then
			echo "${name} already running with pid ${existing_pid}"
			return 0
		fi
		rm -f "${pid_file}"
	fi

	nohup "$@" >"${log_file}" 2>&1 &
	local pid=$!
	echo "${pid}" >"${pid_file}"
	echo "started ${name} with pid ${pid} (log: ${log_file})"
}

stop_process() {
	local name="$1"
	local pid_file
	pid_file="$(pid_file_for "${name}")"

	if [[ ! -f "${pid_file}" ]]; then
		echo "${name} not running"
		return 0
	fi

	local pid
	pid="$(cat "${pid_file}")"
	if kill -0 "${pid}" >/dev/null 2>&1; then
		kill "${pid}"
		echo "stopped ${name} (${pid})"
	else
		echo "${name} pid file was stale (${pid})"
	fi

	rm -f "${pid_file}"
}

print_health() {
	local label="$1"
	local url="$2"

	if curl -fsS "${url}" >/dev/null 2>&1; then
		echo "${label}: up"
	else
		echo "${label}: down"
	fi
}
