# Architecture

## Goal

Build a lightweight Linux observability tool for a single microservice.

## Components

1. Go HTTP service
   - `/health`
   - `/work/cpu`
   - `/work/io`
   - `/metrics`

2. Python collector
   - Reads Linux procfs metrics
   - Scrapes service-level metrics
   - Writes timestamped samples to SQLite

3. SQLite storage
   - `system_metrics`
   - `service_metrics`
   - `load_runs`

4. FastAPI dashboard
   - Lists experiment runs
   - Displays CPU, memory, disk, network, request rate, and latency charts

5. Load generation
   - Uses `wrk`
   - CPU-bound and I/O-bound experiments

## Data flow

```text
wrk -> Go service -> /metrics
              |
              v
Python collector -> SQLite -> FastAPI dashboard
              ^
              |
          /proc filesystem
