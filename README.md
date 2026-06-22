# Microservice Observability Tool

This project builds a small observability pipeline around a Go microservice, a Linux procfs collector, Prometheus, Pushgateway, and Locust. The intended target is a Raspberry Pi, but the core service and instrumentation can be validated locally before touching the Pi.

## Current implementation

- Go HTTP service on port `8080`
- Prometheus scrape endpoint at `/metrics`
- CPU-bound and I/O-bound workload endpoints
- Python collector for host CPU and memory metrics
- 5-second metric push cycle to Pushgateway
- Prometheus scrape config
- Locust load script for repeatable HTTP pressure
- FastAPI dashboard stub for future UI work

## System overview

Application path:

```text
Locust -> Go service -> /metrics -> Prometheus
```

Host path:

```text
/proc filesystem -> Python collector -> Pushgateway -> Prometheus
```

## What each part does

- [service/main.go](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/service/main.go): runs the web service and exposes application metrics
- [collector/main.py](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/collector/main.py): reads host metrics from procfs and pushes them every 5 seconds
- [deploy/prometheus.yml](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/deploy/prometheus.yml): tells Prometheus to scrape the service and Pushgateway
- [scripts/locustfile.py](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/scripts/locustfile.py): defines controlled HTTP traffic patterns
- [dashboard/app.py](/Users/malhardamle/Desktop/side_projects/microservice-observability-tool/dashboard/app.py): placeholder FastAPI app for future dashboard work

## Why `/proc/stat` for CPU usage

`/proc/cpuinfo` on Raspberry Pi is useful for model and hardware metadata, but not live CPU usage. Live per-core utilization comes from `/proc/stat`, so the collector uses:

- `/proc/stat` for `cpu`, `cpu0`, `cpu1`, ... utilization
- `/proc/cpuinfo` for Raspberry Pi hardware labels
- `/proc/meminfo` for memory totals and availability

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
curl http://127.0.0.1:8080/work/cpu
curl http://127.0.0.1:8080/work/io
curl -s http://127.0.0.1:8080/metrics | grep observability
```

Collector:

```bash
cd /Users/malhardamle/Desktop/side_projects/microservice-observability-tool
python3 -m py_compile collector/main.py
python3 collector/main.py --help
```

Raspberry Pi cross-build:

```bash
cd /Users/malhardamle/Desktop/side_projects/microservice-observability-tool/service
GOOS=linux GOARCH=arm64 go build -o service-linux-arm64
```

## Prometheus flow

1. The Go service exposes application metrics at `http://127.0.0.1:8080/metrics`.
2. The collector samples host CPU and memory every 5 seconds.
3. The collector pushes host metrics to Pushgateway on `http://127.0.0.1:9091`.
4. Prometheus scrapes both targets every 5 seconds for time-series storage and querying.

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

From the collector:

- `raspberry_pi_cpu_usage_percent{cpu="cpu0"}`
- `raspberry_pi_memory_used_percent`
- `raspberry_pi_memory_used_bytes`
- `raspberry_pi_info{model="...",hardware="..."}`

## Friend's Pi constraints

If this is running on a friend's Raspberry Pi, prefer a user-space demo:

- do not require `sudo`
- do not install system services
- do not modify boot, DNS, or firewall settings
- run Prometheus and Pushgateway from a home-directory workspace

That keeps the demo reversible and avoids changing machine-wide configuration.
