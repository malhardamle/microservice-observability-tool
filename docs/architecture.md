# Architecture

## Goal

Build a lightweight Linux observability tool for a single microservice, with the Raspberry Pi acting as both the workload host and the machine being observed.

## Components

1. Go HTTP service
   - `/health`
   - `/work/cpu`
   - `/work/io`
   - `/work/mem`
   - `/metrics`
   - exposes Prometheus application metrics
   - supports parameterized workload sizing through query params

2. Python collector
   - wraps `mpstat` for CPU utilization
   - wraps `vmstat` for memory footprint
   - wraps `sar -n DEV` for network bandwidth
   - wraps `iostat` for disk bandwidth
   - optionally wraps `pidstat` for app-scoped CPU, memory, and disk I/O by PID
   - can auto-discover the app PID from a listening TCP port with `ss`
   - reads `/proc/cpuinfo` for hardware metadata
   - pushes metrics to Prometheus Pushgateway every 10 seconds

3. Pushgateway
   - receives pushed host metrics from the collector
   - exposes them for Prometheus scraping

4. Prometheus
   - scrapes the Go service `/metrics`
   - scrapes Pushgateway
   - stores time-series data for application and host metrics

5. Grafana
   - queries Prometheus
   - visualizes application and host metrics during experiments

6. Load generation
   - uses Locust
   - drives CPU-bound, I/O-bound, and memory-bound HTTP experiments

7. FastAPI dashboard
   - current status: stub only
   - future role: experiment views and charts if a custom UI is still needed

## Data flow

```text
Locust/manual curls -> Go service -> /metrics -> Prometheus -> Grafana

mpstat/vmstat/sar/iostat -> Python collector -> Pushgateway -> Prometheus -> Grafana
```

## Metrics model

### Application metrics

Collected inside the Go service with the Prometheus Go client:

- `observability_http_requests_total`
- `observability_http_errors_total`
- `observability_http_request_duration_seconds`
- `observability_work_cpu_duration_seconds`
- `observability_work_io_duration_seconds`
- `observability_work_mem_duration_seconds`

### Host metrics

Collected by the Python Linux-tool collector:

- `raspberry_pi_cpu_usage_percent{cpu="cpu0"}`
- `raspberry_pi_memory_total_bytes`
- `raspberry_pi_memory_available_bytes`
- `raspberry_pi_memory_free_bytes`
- `raspberry_pi_memory_used_bytes`
- `raspberry_pi_memory_used_percent`
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

## Current experiment shape

The current Raspberry Pi setup is sufficient for live experiments:

- workload inputs are controlled through HTTP query params
- application-side timing is captured by Prometheus histograms in the service
- host-side CPU, memory, network, and disk behavior is sampled through Linux system tools and pushed through Pushgateway
- app-scoped CPU, memory, and disk I/O can be sampled separately in PID mode, either from an explicit PID, a PID file, or port-based auto-discovery
- Grafana visualizes both streams from Prometheus on a single dashboard

This makes it possible to compare:

- requested workload intensity, such as `iterations`, `mb`, and `hold_ms`
- observed handler timing in the service
- observed CPU, memory, network, and disk behavior on the Pi
- optionally, observed CPU, memory, and disk I/O for the service process alone
- with port discovery, service restarts do not require manually updating the collector PID target

## Deployment assumptions

- The safest target deployment is a user-space run on the Raspberry Pi.
- Avoid system-wide changes when using a friend's Pi.
- Prometheus and Pushgateway can be run from a home-directory workspace without `sudo`.
- The service, collector, and load scripts should all run as an ordinary user.
