#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/pi-common.sh"

stop_process collector
stop_process prometheus
stop_process pushgateway
stop_process service

