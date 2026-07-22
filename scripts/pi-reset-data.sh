#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/pi-common.sh"

stop_if_running() {
	local name="$1"
	local pid_file
	pid_file="$(pid_file_for "${name}")"

	if [[ -f "${pid_file}" ]]; then
		stop_process "${name}"
	fi
}

stop_if_running collector
stop_if_running prometheus
stop_if_running pushgateway

rm -rf "${PROMETHEUS_DATA_DIR}"
mkdir -p "${PROMETHEUS_DATA_DIR}"
echo "cleared prometheus data at ${PROMETHEUS_DATA_DIR}"

if curl -fsS -X PUT "${PUSHGATEWAY_URL}/api/v1/admin/wipe" >/dev/null 2>&1; then
	echo "wiped pushgateway metrics"
else
	echo "pushgateway wipe skipped (service not running or admin API unavailable)"
fi
