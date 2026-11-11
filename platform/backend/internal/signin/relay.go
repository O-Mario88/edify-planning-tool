package signin

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// HTTPRelay hands security events to the existing application, which still
// owns notifications: it raises the Admin security incident and notifies the
// administrators (apps/accounts/security_event_relay.py). Server to server,
// with the internal key.
type HTTPRelay struct {
	base, key string
	http      *http.Client
}

// NewHTTPRelay returns a relay, or nil when either half is not configured.
func NewHTTPRelay(base, key string) *HTTPRelay {
	if strings.TrimSpace(base) == "" || strings.TrimSpace(key) == "" {
		return nil
	}
	return &HTTPRelay{base: strings.TrimRight(base, "/"), key: key, http: &http.Client{Timeout: 15 * time.Second}}
}

// Report delivers one event.
func (r *HTTPRelay) Report(ctx context.Context, event SecurityEvent) error {
	payload, err := json.Marshal(map[string]any{
		"kind": event.Kind, "userId": event.UserID, "streak": event.Streak, "locked": event.Locked,
	})
	if err != nil {
		return err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost,
		r.base+"/api/auth/internal/security-events", bytes.NewReader(payload))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Edify-Internal-Key", r.key)
	response, err := r.http.Do(request)
	if err != nil {
		return err
	}
	defer func() { _ = response.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
	if response.StatusCode >= 300 {
		return fmt.Errorf("status %d: %s", response.StatusCode, strings.TrimSpace(string(raw)))
	}
	return nil
}
