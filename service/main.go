package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"
)

type HealthResponse struct {
	Status string `json:"status"`
}

type MetricsResponse struct {
	RequestCount  int64   `json:"request_count"`
	ErrorCount    int64   `json:"error_count"`
	RequestRate   float64 `json:"request_rate"`
	LatencyP50Ms float64 `json:"latency_p50_ms"`
	LatencyP95Ms float64 `json:"latency_p95_ms"`
	LatencyP99Ms float64 `json:"latency_p99_ms"`
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)

	if err := json.NewEncoder(w).Encode(payload); err != nil {
		log.Printf("failed to encode response: %v", err)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, HealthResponse{Status: "ok"})
}

func cpuWorkHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	total := 0
	for i := 0; i < 50_000_000; i++ {
		total += i % 7
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"workload":   "cpu",
		"result":     total,
		"elapsed_ms": time.Since(start).Milliseconds(),
	})
}

func ioWorkHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	time.Sleep(25 * time.Millisecond)

	writeJSON(w, http.StatusOK, map[string]any{
		"workload":   "io",
		"elapsed_ms": time.Since(start).Milliseconds(),
	})
}

func metricsHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, MetricsResponse{
		RequestCount:  0,
		ErrorCount:    0,
		RequestRate:   0,
		LatencyP50Ms: 0,
		LatencyP95Ms: 0,
		LatencyP99Ms: 0,
	})
}

func main() {
	mux := http.NewServeMux()

	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/work/cpu", cpuWorkHandler)
	mux.HandleFunc("/work/io", ioWorkHandler)
	mux.HandleFunc("/metrics", metricsHandler)

	addr := ":8080"
	log.Printf("service listening on %s", addr)

	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}