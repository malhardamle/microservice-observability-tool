package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestIOWorkHandlerPerformsRealDiskIO(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/work/io?mb=2", nil)
	recorder := httptest.NewRecorder()

	ioWorkHandler(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", recorder.Code)
	}

	var payload struct {
		Workload     string `json:"workload"`
		MB           int    `json:"mb"`
		BytesWritten int64  `json:"bytes_written"`
		BytesRead    int64  `json:"bytes_read"`
	}

	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	expectedBytes := int64(2 * 1024 * 1024)
	if payload.Workload != "io" {
		t.Fatalf("expected workload io, got %q", payload.Workload)
	}
	if payload.MB != 2 {
		t.Fatalf("expected mb=2, got %d", payload.MB)
	}
	if payload.BytesWritten != expectedBytes {
		t.Fatalf("expected bytes_written=%d, got %d", expectedBytes, payload.BytesWritten)
	}
	if payload.BytesRead != expectedBytes {
		t.Fatalf("expected bytes_read=%d, got %d", expectedBytes, payload.BytesRead)
	}
}

func TestIOWorkHandlerRejectsInvalidMB(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/work/io?mb=0", nil)
	recorder := httptest.NewRecorder()

	ioWorkHandler(recorder, req)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", recorder.Code)
	}
}
