package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"runtime/debug"
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
	memWorkDuration = promauto.NewHistogram(
		prometheus.HistogramOpts{
			Name:    "observability_work_mem_duration_seconds",
			Help:    "Execution time for the memory-bound workload handler.",
			Buckets: prometheus.DefBuckets,
		},
	)
)

const (
	defaultMemoryWorkloadMB     = 64
	defaultMemoryWorkloadHoldMS = 250
	maxMemoryWorkloadMB         = 512
	maxMemoryWorkloadHoldMS     = 10000
	defaultCPUWorkIterations    = 50_000_000
	maxCPUWorkIterations        = 500_000_000
	defaultIOWorkloadMB         = 32
	maxIOWorkloadMB             = 256
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
	iterations, err := parsePositiveIntParam(r, "iterations", defaultCPUWorkIterations, maxCPUWorkIterations)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "iterations must be a positive integer up to 500000000",
		})
		return
	}

	start := time.Now()

	total := 0
	for i := 0; i < iterations; i++ {
		total += i % 7
	}

	elapsed := time.Since(start)
	cpuWorkDuration.Observe(elapsed.Seconds())

	writeJSON(w, http.StatusOK, map[string]any{
		"workload":   "cpu",
		"iterations": iterations,
		"result":     total,
		"elapsed_ms": elapsed.Milliseconds(),
	})
}

func ioWorkHandler(w http.ResponseWriter, r *http.Request) {
	mb, err := parsePositiveIntParam(r, "mb", defaultIOWorkloadMB, maxIOWorkloadMB)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "mb must be a positive integer up to 256",
		})
		return
	}

	start := time.Now()
	bytesWritten, bytesRead, err := runDiskWorkload(mb)
	if err != nil {
		log.Printf("disk workload failed: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{
			"error": "disk workload failed",
		})
		return
	}

	elapsed := time.Since(start)
	ioWorkDuration.Observe(elapsed.Seconds())

	writeJSON(w, http.StatusOK, map[string]any{
		"workload":      "io",
		"mb":            mb,
		"bytes_written": bytesWritten,
		"bytes_read":    bytesRead,
		"elapsed_ms":    elapsed.Milliseconds(),
	})
}

func runDiskWorkload(mb int) (int64, int64, error) {
	tempFile, err := os.CreateTemp("", "observability-io-*")
	if err != nil {
		return 0, 0, err
	}

	path := tempFile.Name()
	defer func() {
		_ = tempFile.Close()
		_ = os.Remove(path)
	}()

	chunk := make([]byte, 1024*1024)
	for i := range chunk {
		chunk[i] = byte(i % 251)
	}

	var bytesWritten int64
	for i := 0; i < mb; i++ {
		written, writeErr := tempFile.Write(chunk)
		bytesWritten += int64(written)
		if writeErr != nil {
			return bytesWritten, 0, writeErr
		}
	}

	if err := tempFile.Sync(); err != nil {
		return bytesWritten, 0, err
	}

	if _, err := tempFile.Seek(0, 0); err != nil {
		return bytesWritten, 0, err
	}

	bytesRead, err := io.Copy(io.Discard, tempFile)
	if err != nil {
		return bytesWritten, bytesRead, err
	}

	return bytesWritten, bytesRead, nil
}

func parsePositiveIntParam(r *http.Request, name string, defaultValue int, maxValue int) (int, error) {
	raw := r.URL.Query().Get(name)
	if raw == "" {
		return defaultValue, nil
	}

	value, err := strconv.Atoi(raw)
	if err != nil {
		return 0, err
	}
	if value <= 0 || value > maxValue {
		return 0, strconv.ErrSyntax
	}

	return value, nil
}

func memWorkHandler(w http.ResponseWriter, r *http.Request) {
	mb, err := parsePositiveIntParam(r, "mb", defaultMemoryWorkloadMB, maxMemoryWorkloadMB)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "mb must be a positive integer up to 512",
		})
		return
	}

	holdMS, err := parsePositiveIntParam(r, "hold_ms", defaultMemoryWorkloadHoldMS, maxMemoryWorkloadHoldMS)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "hold_ms must be a positive integer up to 10000",
		})
		return
	}

	start := time.Now()
	sizeBytes := mb * 1024 * 1024
	buffer := make([]byte, sizeBytes)

	for i := 0; i < len(buffer); i += 4096 {
		buffer[i] = byte(i % 251)
	}
	if len(buffer) > 0 {
		buffer[len(buffer)-1] = 1
	}

	time.Sleep(time.Duration(holdMS) * time.Millisecond)

	buffer = nil
	debug.FreeOSMemory()

	elapsed := time.Since(start)
	memWorkDuration.Observe(elapsed.Seconds())

	writeJSON(w, http.StatusOK, map[string]any{
		"workload":         "memory",
		"allocated_mb":     mb,
		"hold_ms":          holdMS,
		"freed_after_work": true,
		"elapsed_ms":       elapsed.Milliseconds(),
	})
}

func main() {
	mux := http.NewServeMux()

	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/work/cpu", cpuWorkHandler)
	mux.HandleFunc("/work/io", ioWorkHandler)
	mux.HandleFunc("/work/mem", memWorkHandler)
	mux.Handle("/metrics", promhttp.Handler())

	addr := ":8080"
	log.Printf("service listening on %s", addr)

	if err := http.ListenAndServe(addr, metricsMiddleware(mux)); err != nil {
		log.Fatal(err)
	}
}
