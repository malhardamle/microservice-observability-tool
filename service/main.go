package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type HealthResponse struct {
	Status string `json:"status"`
}

type MetricsResponse struct {
	RequestCount uint64  `json:"request_count"`
	ErrorCount   uint64  `json:"error_count"`
	RequestRate  float64 `json:"request_rate"`
	LatencyP50Ms float64 `json:"latency_p50_ms"`
	LatencyP95Ms float64 `json:"latency_p95_ms"`
	LatencyP99Ms float64 `json:"latency_p99_ms"`
}

var (
	requestCounter = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "observability_http_requests_total",
			Help: "Total HTTP requests handled by the service.",
		},
		[]string{"method", "path", "status"},
	)
	errorCounter = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "observability_http_errors_total",
			Help: "Total HTTP responses with 5xx status codes.",
		},
		[]string{"method", "path", "status"},
	)
	requestDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "observability_http_request_duration_seconds",
			Help:    "HTTP request duration in seconds.",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"method", "path"},
	)
	cpuWorkDuration = promauto.NewHistogram(
		prometheus.HistogramOpts{
			Name:    "observability_work_cpu_duration_seconds",
			Help:    "Execution time for the CPU-bound workload handler.",
			Buckets: prometheus.DefBuckets,
		},
	)
	ioWorkDuration = promauto.NewHistogram(
		prometheus.HistogramOpts{
			Name:    "observability_work_io_duration_seconds",
			Help:    "Execution time for the IO-bound workload handler.",
			Buckets: prometheus.DefBuckets,
		},
	)
)

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)

	if err := json.NewEncoder(w).Encode(payload); err != nil {
		log.Printf("failed to encode response: %v", err)
	}
}

type statusRecorder struct {
	http.ResponseWriter
	statusCode int
}

func newStatusRecorder(w http.ResponseWriter) *statusRecorder {
	return &statusRecorder{
		ResponseWriter: w,
		statusCode:     http.StatusOK,
	}
}

func (sr *statusRecorder) WriteHeader(statusCode int) {
	sr.statusCode = statusCode
	sr.ResponseWriter.WriteHeader(statusCode)
}

func metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		recorder := newStatusRecorder(w)

		next.ServeHTTP(recorder, r)

		status := strconv.Itoa(recorder.statusCode)
		path := r.URL.Path
		method := r.Method
		durationSeconds := time.Since(start).Seconds()

		requestCounter.WithLabelValues(method, path, status).Inc()
		requestDuration.WithLabelValues(method, path).Observe(durationSeconds)

		if recorder.statusCode >= http.StatusInternalServerError {
			errorCounter.WithLabelValues(method, path, status).Inc()
		}
	})
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

	elapsed := time.Since(start)
	cpuWorkDuration.Observe(elapsed.Seconds())

	writeJSON(w, http.StatusOK, map[string]any{
		"workload":   "cpu",
		"result":     total,
		"elapsed_ms": elapsed.Milliseconds(),
	})
}

func ioWorkHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	time.Sleep(25 * time.Millisecond)

	elapsed := time.Since(start)
	ioWorkDuration.Observe(elapsed.Seconds())

	writeJSON(w, http.StatusOK, map[string]any{
		"workload":   "io",
		"elapsed_ms": elapsed.Milliseconds(),
	})
}

func main() {
	mux := http.NewServeMux()

	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/work/cpu", cpuWorkHandler)
	mux.HandleFunc("/work/io", ioWorkHandler)
	mux.Handle("/metrics", promhttp.Handler())

	addr := ":8080"
	log.Printf("service listening on %s", addr)

	if err := http.ListenAndServe(addr, metricsMiddleware(mux)); err != nil {
		log.Fatal(err)
	}
}
