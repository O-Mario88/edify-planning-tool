package accounts

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

// HTTPRelay posts account events to the existing application
// (apps/accounts/account_event_relay.py), server to server with the internal
// key.
type HTTPRelay struct {
	base, key string
	http      *http.Client
}

// NewHTTPRelay returns a relay, or nil when either half is not configured.
func NewHTTPRelay(base, key string) *HTTPRelay {
	if strings.TrimSpace(base) == "" || strings.TrimSpace(key) == "" {
		return nil
	}
	return &HTTPRelay{base: strings.TrimRight(base, "/"), key: key, http: &http.Client{Timeout: 25 * time.Second}}
}

// Report delivers one event.
func (r *HTTPRelay) Report(ctx context.Context, event Event) error {
	body := map[string]string{"kind": event.Kind, "userId": event.UserID}
	if event.SubjectID != "" {
		body["subjectId"] = event.SubjectID
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, r.base+"/api/auth/internal/account-events", bytes.NewReader(payload))
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
