# Microservice Observability Tool

Lightweight observability pipeline for a Go microservice running on Raspberry Pi. The project ties application workloads to real host behavior by exposing synthetic stress endpoints, collecting both app-level and Linux host metrics, routing them through Pushgateway and Prometheus, and visualizing them in Grafana.

## What I built

- Go HTTP service with parameterized CPU, memory, and disk stress endpoints
- Prometheus instrumentation exposed at `/metrics`
- Python collector for Linux CPU, memory, network, and disk metrics
- Pushgateway + Prometheus pipeline for time-series collection
- Grafana dashboards for comparing request behavior against host resource signals
- Locust script for repeatable load generation

## Architecture

Application path:

```text
Load test / curl -> Go service -> /metrics -> Prometheus -> Grafana
```

Host path:

```text
mpstat / vmstat / sar / iostat -> Python collector -> Pushgateway -> Prometheus -> Grafana
```

## Key files

- `service/main.go`: Go service and Prometheus app metrics
- `collector/main.py`: host/app metric collector and Pushgateway publisher
- `deploy/prometheus.yml`: Prometheus scrape config
- `scripts/locustfile.py`: repeatable HTTP traffic patterns
- `scripts/pi-start.sh`: Raspberry Pi helper for starting the local stack

## What this project demonstrates

- How app-level load shows up in request latency and service metrics
- How host-level CPU, memory, network, and disk signals change under synthetic workloads
- Why app-issued I/O and physical disk reads are not always the same thing
- How Linux page cache can hide disk reads even when the application is doing heavy file I/O

## Main learning

The most useful takeaway was separating application demand from host-level effects. CPU-heavy and memory-heavy workloads produced direct, intuitive changes in service timing and host utilization, while I/O-heavy workloads were more nuanced because Linux caching could absorb much of the read activity before it showed up as physical disk pressure.

## Validation status

This project was validated end to end on a headless Raspberry Pi:

- service endpoints responded correctly
- collector pushed Linux metrics to Pushgateway
- Prometheus scraped both service and collector outputs
- Grafana visualized app and host behavior together

## Running it

### Service

```bash
cd service
go test ./...
go run .
```

### Collector

```bash
python3 -m py_compile collector/main.py
python3 collector/main.py --help
```

### Quick checks

```bash
curl http://127.0.0.1:8080/health
curl "http://127.0.0.1:8080/work/cpu?iterations=100000000"
curl "http://127.0.0.1:8080/work/io?mb=64"
curl "http://127.0.0.1:8080/work/mem?mb=128&hold_ms=1000"
curl -s http://127.0.0.1:8080/metrics | grep observability
```

### Raspberry Pi helpers

```bash
bash scripts/pi-start.sh
bash scripts/pi-status.sh
bash scripts/pi-stop.sh
bash scripts/pi-reset-data.sh
```

Runtime packages on Pi:

```bash
sudo apt-get install -y sysstat procps iproute2
```

## Example metrics

From the service:

- `observability_http_requests_total`
- `observability_http_request_duration_seconds`
- `observability_work_cpu_duration_seconds`
- `observability_work_io_duration_seconds`
- `observability_work_mem_duration_seconds`

From the collector:

- `raspberry_pi_cpu_usage_percent`
- `raspberry_pi_memory_used_percent`
- `raspberry_pi_network_receive_bytes_per_second`
- `raspberry_pi_disk_read_bytes_per_second`
- `raspberry_pi_disk_write_bytes_per_second`

## Scope

This repo is intentionally a small, finished project rather than a full production observability platform. The goal was to build a credible end-to-end experiment, validate it on Raspberry Pi, and capture the practical systems insight from the results.
