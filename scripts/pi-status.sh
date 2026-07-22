#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/pi-common.sh"

show_process() {
	local name="$1"
	local pid_file
	pid_file="$(pid_file_for "${name}")"

	if [[ -f "${pid_file}" ]]; then
		local pid
		pid="$(cat "${pid_file}")"
		if kill -0 "${pid}" >/dev/null 2>&1; then
			echo "${name}: pid ${pid}"
			ps -p "${pid}" -o pid=,etime=,command=
			return
		fi
		echo "${name}: stale pid file (${pid})"
		return
	fi

	echo "${name}: not running"
}

echo "processes"
show_process service
show_process pushgateway
show_process prometheus
show_process collector

echo
echo "health"
print_health service "http://127.0.0.1:${SERVICE_PORT}/health"
print_health pushgateway "http://127.0.0.1:${PUSHGATEWAY_PORT}/-/ready"
print_health prometheus "http://127.0.0.1:${PROMETHEUS_PORT}/-/healthy"
print_health grafana "http://127.0.0.1:${GRAFANA_PORT}/api/health"

echo
echo "prometheus targets"
curl -fsS "http://127.0.0.1:${PROMETHEUS_PORT}/api/v1/targets" || true
echo
