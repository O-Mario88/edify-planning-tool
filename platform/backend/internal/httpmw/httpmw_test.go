package httpmw

import (
	"bytes"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAccessLogRedactsSMSDeliveryReportSecret(t *testing.T) {
	var logs bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&logs, nil))
	handler := Chain(logger, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	const secret = "super-secret-callback-token-987654"
	req := httptest.NewRequest(http.MethodPost, "/sms/delivery-report/"+secret+"?id=123", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204", rec.Code)
	}
	logged := logs.String()
	if strings.Contains(logged, secret) {
		t.Fatalf("access log leaked SMS webhook secret: %s", logged)
	}
	if !strings.Contains(logged, "/sms/delivery-report/[redacted]") {
		t.Fatalf("access log did not record redacted path: %s", logged)
	}
	if rec.Header().Get("X-Content-Type-Options") != "nosniff" || rec.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("missing security headers: %v", rec.Header())
	}
}

func TestRecoverConvertsPanicIntoStructured500(t *testing.T) {
	var logs bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&logs, nil))
	handler := Chain(logger, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		panic("boom")
	}))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/test", nil))
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), `"code":"internal"`) {
		t.Fatalf("unexpected body: %s", rec.Body.String())
	}
}

func TestCORSRefusesDisallowedPreflightAndAllowsListedOrigin(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	handler := CORS([]string{"https://staging.example.org"}, next)

	denied := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodOptions, "/rpc", nil)
	req.Header.Set("Origin", "https://evil.example")
	req.Header.Set("Access-Control-Request-Method", "POST")
	handler.ServeHTTP(denied, req)
	if denied.Code != http.StatusForbidden {
		t.Fatalf("disallowed preflight = %d, want 403", denied.Code)
	}

	allowed := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodOptions, "/rpc", nil)
	req2.Header.Set("Origin", "https://staging.example.org")
	req2.Header.Set("Access-Control-Request-Method", "POST")
	handler.ServeHTTP(allowed, req2)
	if allowed.Code != http.StatusNoContent || allowed.Header().Get("Access-Control-Allow-Origin") != "https://staging.example.org" {
		t.Fatalf("allowed preflight = %d, header = %q", allowed.Code, allowed.Header().Get("Access-Control-Allow-Origin"))
	}
}
