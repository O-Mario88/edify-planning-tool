package notifymail

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestResendSaysExactlyWhatHappened(t *testing.T) {
	var gotKey, gotAuth string
	var gotBody map[string]any
	status := http.StatusOK
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey, gotAuth = r.Header.Get("Idempotency-Key"), r.Header.Get("Authorization")
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"id":"re_123","echo":"the message"}`))
	}))
	defer server.Close()
	mailer := Resend{Provider: "resend", APIKey: "test-key", URL: server.URL, Client: server.Client()}
	message := Message{To: "grace@example.org", Subject: "Edify: a new planning notification", Text: "t", HTML: "<p>h</p>"}

	got := mailer.Deliver(context.Background(), message, "edify-notification-d1")
	if !got.Accepted || got.ProviderID != "re_123" {
		t.Fatalf("accepted send = %+v", got)
	}
	if gotKey != "edify-notification-d1" || gotAuth != "Bearer test-key" || gotBody["from"] != defaultFrom ||
		gotBody["html"] != "<p>h</p>" {
		t.Fatalf("request: key %q auth %q body %v", gotKey, gotAuth, gotBody)
	}
	for code, retryable := range map[int]bool{http.StatusServiceUnavailable: true, http.StatusTooManyRequests: true,
		http.StatusBadRequest: false, http.StatusUnauthorized: false} {
		status = code
		got := mailer.Deliver(context.Background(), message, "k")
		if got.Accepted || got.Retryable != retryable || got.Error != "HTTP "+itoa(code) {
			t.Errorf("status %d = %+v", code, got)
		}
	}
}

func TestResendIsNotConfiguredWithoutItsKey(t *testing.T) {
	for _, m := range []Resend{{Provider: "resend"}, {APIKey: "k"}, {Provider: "console", APIKey: "k"}} {
		if m.Configured() {
			t.Fatalf("%+v reads as configured", m)
		}
		if got := m.Deliver(context.Background(), Message{}, ""); got.Accepted || got.Retryable || got.Error != "not_configured" {
			t.Fatalf("unconfigured send = %+v", got)
		}
	}
}

func itoa(n int) string {
	b, _ := json.Marshal(n)
	return string(b)
}
