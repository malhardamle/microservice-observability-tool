#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/pi-common.sh"

require_command go
require_command python3
require_command curl
require_command ss

PUSHGATEWAY_DIR="${PUSHGATEWAY_DIR:-$(find_binary_dir 'pushgateway-*.linux-arm64')}"
PROMETHEUS_DIR="${PROMETHEUS_DIR:-$(find_binary_dir 'prometheus-*.linux-arm64')}"
SERVICE_BINARY="${SERVICE_BINARY:-${BIN_DIR}/service}"

if [[ -z "${PUSHGATEWAY_DIR}" || ! -x "${PUSHGATEWAY_DIR}/pushgateway" ]]; then
	echo "pushgateway binary not found. Set PUSHGATEWAY_DIR or install the arm64 release under \$HOME." >&2
	exit 1
fi

if [[ -z "${PROMETHEUS_DIR}" || ! -x "${PROMETHEUS_DIR}/prometheus" ]]; then
	echo "prometheus binary not found. Set PROMETHEUS_DIR or install the arm64 release under \$HOME." >&2
	exit 1
fi

ensure_port_free "${SERVICE_PORT}" "service"
ensure_port_free "${PUSHGATEWAY_PORT}" "pushgateway"
ensure_port_free "${PROMETHEUS_PORT}" "prometheus"

(
	cd "${REPO_ROOT}/service"
	go build -o "${SERVICE_BINARY}" .
)

start_background service "${SERVICE_BINARY}"
start_background pushgateway "${PUSHGATEWAY_DIR}/pushgateway" --web.listen-address=":${PUSHGATEWAY_PORT}"
start_background prometheus "${PROMETHEUS_DIR}/prometheus" --config.file="${PROMETHEUS_CONFIG}" --web.listen-address=":${PROMETHEUS_PORT}"
start_background collector python3 "${REPO_ROOT}/collector/main.py" --discover-port "${SERVICE_PORT}" --interval "${COLLECTOR_INTERVAL}" --pushgateway "${PUSHGATEWAY_URL}"

sleep 3

echo
echo "health checks"
print_health service "http://127.0.0.1:${SERVICE_PORT}/health"
print_health pushgateway "http://127.0.0.1:${PUSHGATEWAY_PORT}/-/ready"
print_health prometheus "http://127.0.0.1:${PROMETHEUS_PORT}/-/healthy"
print_health grafana "http://127.0.0.1:${GRAFANA_PORT}/api/health"
