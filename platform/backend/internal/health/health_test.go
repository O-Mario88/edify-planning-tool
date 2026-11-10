package health_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/health"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/httpmw"
)

type pinger struct{ err error }

func (p pinger) Ping(context.Context) error { return p.err }

func serve(t *testing.T, database pinger, path string, headers map[string]string) (*http.Response, map[string]any) {
	t.Helper()
	mux := http.NewServeMux()
	health.NewHandler("test", "abc123", database).Register(mux)
	mux.HandleFunc("GET /panic", func(http.ResponseWriter, *http.Request) { panic("boom") })

	request := httptest.NewRequest(http.MethodGet, path, nil)
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	recorder := httptest.NewRecorder()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	httpmw.Chain(logger, mux).ServeHTTP(recorder, request)

	var body map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("response is not JSON: %q", recorder.Body.String())
	}
	return recorder.Result(), body
}

func TestLivenessNeverTouchesTheDatabase(t *testing.T) {
	response, body := serve(t, pinger{err: errors.New("down")}, "/healthz", nil)
	if response.StatusCode != http.StatusOK || body["status"] != "ok" || body["release"] != "abc123" {
		t.Fatalf("got %d %v", response.StatusCode, body)
	}
}

func TestReadiness(t *testing.T) {
	response, body := serve(t, pinger{}, "/readyz", nil)
	if response.StatusCode != http.StatusOK || body["status"] != "ok" {
		t.Fatalf("got %d %v", response.StatusCode, body)
	}

	response, body = serve(t, pinger{err: errors.New("dial tcp 10.0.0.5:5432: refused")}, "/readyz", nil)
	if response.StatusCode != http.StatusServiceUnavailable || body["status"] != "failed" {
		t.Fatalf("got %d %v", response.StatusCode, body)
	}
	if encoded, _ := json.Marshal(body); strings.Contains(string(encoded), "10.0.0.5") {
		t.Fatalf("readiness leaks connection details: %s", encoded)
	}
}

func TestEveryResponseCarriesTraceAndHardeningHeaders(t *testing.T) {
	const incoming = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
	response, _ := serve(t, pinger{}, "/healthz", map[string]string{
		"X-Request-Id": "mobile-req-0001",
		"traceparent":  incoming,
	})
	if got := response.Header.Get("X-Request-Id"); got != "mobile-req-0001" {
		t.Errorf("request id %q", got)
	}
	traceparent := response.Header.Get("traceparent")
	if !strings.HasPrefix(traceparent, "00-4bf92f3577b34da6a3ce929d0e0e4736-") || traceparent == incoming {
		t.Errorf("traceparent %q must continue the trace with a new span", traceparent)
	}
	if response.Header.Get("X-Content-Type-Options") != "nosniff" || response.Header.Get("Cache-Control") != "no-store" {
		t.Errorf("hardening headers missing: %v", response.Header)
	}
}

func TestPanicBecomesAStructuredError(t *testing.T) {
	response, body := serve(t, pinger{}, "/panic", nil)
	if response.StatusCode != http.StatusInternalServerError || body["code"] != "internal" {
		t.Fatalf("got %d %v", response.StatusCode, body)
	}
	if body["request_id"] == "" || body["request_id"] != response.Header.Get("X-Request-Id") {
		t.Fatalf("the error must carry the request id: %v", body)
	}
	if strings.Contains(body["message"].(string), "boom") {
		t.Fatal("the panic value reached the client")
	}
}

func corsRequest(t *testing.T, allowed []string, method, origin string, preflight bool) *http.Response {
	t.Helper()
	mux := http.NewServeMux()
	health.NewHandler("test", "abc123", pinger{}).Register(mux)
	request := httptest.NewRequest(method, "/healthz", nil)
	if origin != "" {
		request.Header.Set("Origin", origin)
	}
	if preflight {
		request.Header.Set("Access-Control-Request-Method", "POST")
	}
	recorder := httptest.NewRecorder()
	httpmw.CORS(allowed, mux).ServeHTTP(recorder, request)
	return recorder.Result()
}

func TestCORS(t *testing.T) {
	const web = "http://localhost:8082"
	allowed := []string{web}

	t.Run("off by default: no headers for anyone", func(t *testing.T) {
		response := corsRequest(t, nil, http.MethodGet, web, false)
		if response.Header.Get("Access-Control-Allow-Origin") != "" {
			t.Fatalf("headers sent with no origins configured: %v", response.Header)
		}
	})
	t.Run("an allowed origin is echoed, never a wildcard, never credentials", func(t *testing.T) {
		response := corsRequest(t, allowed, http.MethodGet, web, false)
		if got := response.Header.Get("Access-Control-Allow-Origin"); got != web {
			t.Fatalf("allow-origin %q", got)
		}
		if response.Header.Get("Access-Control-Allow-Credentials") != "" {
			t.Fatal("credentials must never be allowed")
		}
		if response.StatusCode != http.StatusOK {
			t.Fatalf("status %d", response.StatusCode)
		}
	})
	t.Run("an allowed preflight is answered without reaching a handler", func(t *testing.T) {
		response := corsRequest(t, allowed, http.MethodOptions, web, true)
		if response.StatusCode != http.StatusNoContent ||
			!strings.Contains(response.Header.Get("Access-Control-Allow-Headers"), "Authorization") {
			t.Fatalf("got %d %v", response.StatusCode, response.Header)
		}
	})
	t.Run("another origin gets no headers and its preflight is refused", func(t *testing.T) {
		response := corsRequest(t, allowed, http.MethodGet, "https://evil.example", false)
		if response.Header.Get("Access-Control-Allow-Origin") != "" {
			t.Fatalf("headers sent to another origin: %v", response.Header)
		}
		preflight := corsRequest(t, allowed, http.MethodOptions, "https://evil.example", true)
		if preflight.StatusCode != http.StatusForbidden {
			t.Fatalf("preflight status %d", preflight.StatusCode)
		}
	})
}
