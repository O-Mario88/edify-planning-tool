package notifymail

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"
)

// resendURL is the provider's one address (apps.core.email).
const resendURL = "https://api.resend.com/emails"

const defaultFrom = "Edify Planning <noreply@edify.org>"

// retryableStatus are _RETRYABLE_STATUS.
var retryableStatus = map[int]bool{408: true, 409: true, 425: true, 429: true, 500: true, 502: true, 503: true, 504: true}

// Result is MailResult.
type Result struct {
	Accepted, Retryable bool
	ProviderID, Error   string
}

// Resend is MailerService with the Resend provider: configured only when
// EMAIL_PROVIDER is "resend" and an API key is set.
type Resend struct {
	Provider, APIKey, From string
	Client                 *http.Client
	// URL is the provider's address; empty is Resend's own.
	URL string
}

// ResendFrom reads the provider settings the existing mailer reads.
func ResendFrom(getenv func(string) string) Resend {
	return Resend{Provider: getenv("EMAIL_PROVIDER"), APIKey: getenv("RESEND_API_KEY"), From: getenv("EMAIL_FROM"),
		Client: &http.Client{Timeout: 15 * time.Second}}
}

// Configured is MailerService.is_configured.
func (r Resend) Configured() bool { return r.Provider == "resend" && r.APIKey != "" }

// Deliver is MailerService.deliver: one send, and exactly what happened.
// Only the status of a refusal is kept: the provider's answer can echo the
// message.
func (r Resend) Deliver(ctx context.Context, m Message, idempotencyKey string) Result {
	if !r.Configured() {
		return Result{Error: "not_configured"}
	}
	from := r.From
	if from == "" {
		from = defaultFrom
	}
	payload := map[string]any{"from": from, "to": m.To, "subject": m.Subject, "text": m.Text}
	if m.HTML != "" {
		payload["html"] = m.HTML
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return Result{Retryable: true, Error: "TypeError"}
	}
	url := r.URL
	if url == "" {
		url = resendURL
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return Result{Retryable: true, Error: "ValueError"}
	}
	req.Header.Set("Authorization", "Bearer "+r.APIKey)
	req.Header.Set("Content-Type", "application/json")
	if idempotencyKey != "" {
		if len(idempotencyKey) > 256 {
			idempotencyKey = idempotencyKey[:256]
		}
		req.Header.Set("Idempotency-Key", idempotencyKey)
	}
	client := r.Client
	if client == nil {
		client = &http.Client{Timeout: 15 * time.Second}
	}
	res, err := client.Do(req)
	if err != nil {
		return Result{Retryable: true, Error: networkErrorName(err)}
	}
	defer res.Body.Close()
	answer, _ := io.ReadAll(io.LimitReader(res.Body, 1<<16))
	if res.StatusCode >= 200 && res.StatusCode < 300 {
		var sent struct {
			ID any `json:"id"`
		}
		id := ""
		if json.Unmarshal(answer, &sent) == nil && sent.ID != nil {
			id = fmt.Sprint(sent.ID)
		}
		if len(id) > 128 {
			id = id[:128]
		}
		return Result{Accepted: true, ProviderID: id}
	}
	return Result{Retryable: retryableStatus[res.StatusCode], Error: fmt.Sprintf("HTTP %d", res.StatusCode)}
}

// networkErrorName is the exception name the existing mailer records for a
// request that never got an answer.
func networkErrorName(err error) string {
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return "TimeoutError"
	}
	return "URLError"
}

// BaseURLFrom is app_base_url: APP_BASE_URL (or the gateway's own
// EDIFY_APP_BASE_URL), else the platform's domain as production settings
// derive it, else the development default.
func BaseURLFrom(getenv func(string) string) string {
	for _, key := range []string{"APP_BASE_URL", "EDIFY_APP_BASE_URL"} {
		if v := getenv(key); v != "" {
			return v
		}
	}
	for _, key := range []string{"DIGITALOCEAN_APP_DOMAIN", "APP_DOMAIN"} {
		if v := getenv(key); v != "" {
			return "https://" + v
		}
	}
	return "http://localhost:3000"
}
