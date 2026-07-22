# Microservice Observability Tool

This project builds a small observability pipeline around a Go microservice, a Linux host-metrics collector, Prometheus, Pushgateway, Grafana, and Locust. The intended target is a Raspberry Pi, but the core service and instrumentation can be validated locally before touching the Pi.

## Current implementation

- Go HTTP service on port `8080`
- Prometheus scrape endpoint at `/metrics`
- Parameterized CPU, I/O, and memory workload endpoints
- Python collector for host CPU, memory, network, and disk metrics
- 10-second metric push cycle to Pushgateway
- Prometheus scrape config
- Grafana dashboard support over Prometheus
- Locust load script for repeatable HTTP pressure
- FastAPI dashboard stub for future UI work

## System overview

Application path:

```text
Locust/manual curls -> Go service -> /metrics -> Prometheus -> Grafana
```

Host path:

```text
mpstat/vmstat/sar/iostat -> Python collector -> Pushgateway -> Prometheus -> Grafana
```

## What each part does

- [service/main.go](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/service/main.go): runs the web service and exposes application metrics
- [collector/main.py](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/collector/main.py): runs `mpstat`, `vmstat`, `sar`, and `iostat`, optionally auto-discovers the service PID from a listening port, and pushes metrics every 10 seconds
- [deploy/prometheus.yml](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/deploy/prometheus.yml): tells Prometheus to scrape the service and Pushgateway
- [scripts/locustfile.py](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/scripts/locustfile.py): defines controlled HTTP traffic patterns
- Grafana: visualizes Prometheus application and host metrics for live experiment monitoring
- [dashboard/app.py](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/dashboard/app.py): placeholder FastAPI app for future dashboard work

## Host metric sources

The collector now wraps standard Linux tooling for macro host metrics:

- `mpstat` for CPU utilization
- `vmstat` for memory footprint
- `sar -n DEV` for network bandwidth
- `iostat` for disk bandwidth

It still reads `/proc/cpuinfo` directly for Raspberry Pi hardware metadata labels.

Optional app-focused mode:

- `--pid <PID>` collects CPU, memory, and disk I/O for a single process with `pidstat`
- `--pid-file <path>` reads the PID from a file before each sample
- `--discover-port <PORT>` auto-discovers the PID from the process listening on that TCP port with `ss`
- network remains host-scoped because per-process bandwidth attribution is not reliable with these tools
- if discovery finds zero or multiple matching PIDs, the collector fails that sample loudly instead of guessing

## Local validation

The service and collector can be validated on your own machine before using the Pi.

Service:

```bash
cd /Users/malhardamle/Desktop/side_projects/microservice-observability-tool/service
go test ./...
go run .
```

Expected checks:

```bash
curl http://127.0.0.1:8080/health
curl "http://127.0.0.1:8080/work/cpu?iterations=100000000"
curl "http://127.0.0.1:8080/work/io?sleep_ms=250"
curl "http://127.0.0.1:8080/work/mem?mb=128&hold_ms=1000"
curl -s http://127.0.0.1:8080/metrics | grep observability
```

Collector:

```bash
cd /Users/malhardamle/Desktop/side_projects/microservice-observability-tool
python3 -m py_compile collector/main.py
python3 collector/main.py --help
```

Example PID-focused collector:

```bash
python3 collector/main.py --pid 12345
```

Recommended Pi command for the Go service on port `8080`:

```bash
python3 collector/main.py --discover-port 8080
```

Pi helper scripts:

```bash
bash scripts/pi-start.sh
bash scripts/pi-status.sh
bash scripts/pi-stop.sh
```

These scripts:

- start the Go service, Pushgateway, Prometheus, and the collector in the background
- write logs under `.pi-runtime/logs`
- store PID files under `.pi-runtime/pids`
- assume Prometheus is exposed on `9092` to avoid collisions with an existing `9090`
- leave Grafana unmanaged, but include it in health checks when it is already running

Runtime dependency note:

```bash
sudo apt-get install -y sysstat procps iproute2
```

Raspberry Pi cross-build:

```bash
cd /Users/malhardamle/Desktop/side_projects/microservice-observability-tool/service
GOOS=linux GOARCH=arm64 go build -o service-linux-arm64
```

## Prometheus flow

1. The Go service exposes application metrics at `http://127.0.0.1:8080/metrics`.
2. The collector samples host CPU, memory, network, and disk metrics every 10 seconds.
3. In PID mode, the collector samples app CPU, memory, and disk I/O for a single process instead of host-wide stats.
4. `--discover-port` resolves the PID from the service's listening socket before each sample, so restarts do not require manual PID updates.
5. The collector pushes host or app-scoped metrics to Pushgateway on `http://127.0.0.1:9091`.
6. Prometheus scrapes both targets every 5 seconds for time-series storage and querying.
7. Grafana reads Prometheus and renders experiment dashboards.

## Raspberry Pi status

The Raspberry Pi validation path is working end to end:

- the Go HTTP service runs on the Pi
- parameterized workload endpoints respond correctly
- the Linux-tool-based collector pushes host metrics to Pushgateway
- Prometheus scrapes both the service and Pushgateway
- Grafana displays application and host metrics through Prometheus

Working endpoints:

```bash
curl http://127.0.0.1:8080/health
curl "http://127.0.0.1:8080/work/cpu?iterations=100000000"
curl "http://127.0.0.1:8080/work/io?sleep_ms=250"
curl "http://127.0.0.1:8080/work/mem?mb=256&hold_ms=3000"
```

Useful experiment dashboard signals:

- `observability_work_cpu_duration_seconds_count`
- `observability_work_mem_duration_seconds_count`
- `raspberry_pi_cpu_usage_percent{cpu!="cpu"}`
- `raspberry_pi_memory_used_percent`
- `raspberry_pi_network_receive_bytes_per_second`
- `raspberry_pi_network_transmit_bytes_per_second`
- `raspberry_pi_disk_read_bytes_per_second`
- `raspberry_pi_disk_write_bytes_per_second`
- `observability_work_cpu_duration_seconds_sum / observability_work_cpu_duration_seconds_count`
- `observability_work_mem_duration_seconds_sum / observability_work_mem_duration_seconds_count`

## Load testing

Open the Locust web UI:

```bash
locust -f /Users/malhardamle/Desktop/side_projects/microservice-observability-tool/scripts/locustfile.py --host http://127.0.0.1:8080
```

Suggested first runs:

- `10` users, spawn rate `2`, duration `2m`
- `25` users, spawn rate `5`, duration `5m`
- compare CPU-heavy and IO-heavy mixes

## Expected metrics

From the service:

- `observability_http_requests_total`
- `observability_http_errors_total`
- `observability_http_request_duration_seconds`
- `observability_work_cpu_duration_seconds`
- `observability_work_io_duration_seconds`
- `observability_work_mem_duration_seconds`

From the collector:

- `raspberry_pi_cpu_usage_percent{cpu="cpu0"}`
- `raspberry_pi_memory_free_bytes`
- `raspberry_pi_memory_used_percent`
- `raspberry_pi_memory_used_bytes`
- `raspberry_pi_network_receive_bytes_per_second{iface="wlan0"}`
- `raspberry_pi_network_transmit_bytes_per_second{iface="wlan0"}`
- `raspberry_pi_disk_read_bytes_per_second{device="mmcblk0"}`
- `raspberry_pi_disk_write_bytes_per_second{device="mmcblk0"}`
- `raspberry_pi_app_cpu_usage_percent{pid="12345"}`
- `raspberry_pi_app_memory_percent{pid="12345"}`
- `raspberry_pi_app_disk_read_bytes_per_second{pid="12345"}`
- `raspberry_pi_app_disk_write_bytes_per_second{pid="12345"}`
- `raspberry_pi_app_scope_info{pid="12345",scope="process",network_scope="unsupported"}`
- `raspberry_pi_info{model="...",hardware="..."}`

## Friend's Pi constraints

If this is running on a friend's Raspberry Pi, prefer a user-space demo:

- do not require `sudo`
- do not install system services
- do not modify boot, DNS, or firewall settings
- run Prometheus and Pushgateway from a home-directory workspace

That keeps the demo reversible and avoids changing machine-wide configuration.
