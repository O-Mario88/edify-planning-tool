package activities

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// Money stays the existing application's until M12 (27.2, 27.8): the save
// asks it what the pricing would refuse before it opens its transaction,
// and asks it to settle the costs to follow once it has committed. Server to
// server, with the internal key (apps.daily_visit_batches.gateway_relay).

// Pricing is what the save asks of the existing application's money rules.
type Pricing interface {
	// DayCheck plays the activity's join of its day and answers the
	// pricing's verdict.
	DayCheck(ctx context.Context, activity map[string]any) (DayVerdict, error)
	// Settle prices what the save kept and announces the visit.
	Settle(ctx context.Context, rows []int64, activityID string) error
}

// HTTPPricing calls the existing application at base.
type HTTPPricing struct {
	base, key string
	client    *http.Client
}

// NewHTTPPricing returns the relay; base is the existing application's
// origin and key its EDIFY_INTERNAL_KEY.
func NewHTTPPricing(base, key string, client *http.Client) *HTTPPricing {
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	return &HTTPPricing{base: strings.TrimRight(base, "/"), key: key, client: client}
}

func (h *HTTPPricing) post(ctx context.Context, path string, body, out any) error {
	payload, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("activities: encoding %s: %w", path, err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, h.base+path, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("activities: %s: %w", path, err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Edify-Internal-Key", h.key)
	resp, err := h.client.Do(req)
	if err != nil {
		return fmt.Errorf("activities: %s: %w", path, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("activities: %s answered %d", path, resp.StatusCode)
	}
	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return fmt.Errorf("activities: reading %s: %w", path, err)
	}
	return nil
}

// DayVerdict is the pricing's answer for one visit: its refusal and where
// the existing save meets it ("preview", before its transaction; "day",
// once the visit has joined its day), and whether the day pools the visit.
type DayVerdict struct {
	Refusal string `json:"refusal"`
	Stage   string `json:"stage"`
	Pooled  bool   `json:"pooled"`
	// Online is the cost revision of a Group Training delivered online
	// (docs/migration/48), which asks no preview and joins no day.
	Online *OnlineCost `json:"online,omitempty"`
}

// DayCheck asks /api/auth/internal/visit-day-check.
func (h *HTTPPricing) DayCheck(ctx context.Context, activity map[string]any) (DayVerdict, error) {
	var answer struct {
		OK bool `json:"ok"`
		DayVerdict
	}
	if err := h.post(ctx, "/api/auth/internal/visit-day-check", map[string]any{"activity": activity}, &answer); err != nil {
		return DayVerdict{}, err
	}
	if !answer.OK {
		return DayVerdict{}, fmt.Errorf("activities: the day check was not answered")
	}
	return answer.DayVerdict, nil
}

// Settle asks /api/auth/internal/costs-to-follow.
func (h *HTTPPricing) Settle(ctx context.Context, rows []int64, activityID string) error {
	var answer struct {
		OK bool `json:"ok"`
	}
	if err := h.post(ctx, "/api/auth/internal/costs-to-follow",
		map[string]any{"rows": rows, "activityId": activityID}, &answer); err != nil {
		return err
	}
	if !answer.OK {
		return fmt.Errorf("activities: the costs to follow were not settled")
	}
	return nil
}

// MoveCheck asks /api/auth/internal/visit-move-check (docs/migration/29).
func (h *HTTPPricing) MoveCheck(ctx context.Context, activityID, date, reason string) (MoveVerdict, error) {
	var answer struct {
		OK bool `json:"ok"`
		MoveVerdict
	}
	if err := h.post(ctx, "/api/auth/internal/visit-move-check",
		map[string]any{"activityId": activityID, "scheduledDate": date, "reason": reason}, &answer); err != nil {
		return MoveVerdict{}, err
	}
	if !answer.OK {
		return MoveVerdict{}, fmt.Errorf("activities: the move check was not answered")
	}
	return answer.MoveVerdict, nil
}

// CancelCheck asks /api/auth/internal/visit-cancel-check (docs/migration/30).
func (h *HTTPPricing) CancelCheck(ctx context.Context, activityID, reason string) (CancelVerdict, error) {
	var answer struct {
		OK bool `json:"ok"`
		CancelVerdict
	}
	if err := h.post(ctx, "/api/auth/internal/visit-cancel-check",
		map[string]any{"activityId": activityID, "reason": reason}, &answer); err != nil {
		return CancelVerdict{}, err
	}
	if !answer.OK {
		return CancelVerdict{}, fmt.Errorf("activities: the cancel check was not answered")
	}
	return answer.CancelVerdict, nil
}

// Announcer tells the existing application's realtime stream that an
// activity Go saved has changed, when no costs follow to say it.
type Announcer interface {
	Announce(ctx context.Context, activityID string) error
}

// Announce asks /api/auth/internal/activity-changed (docs/migration/31).
func (h *HTTPPricing) Announce(ctx context.Context, activityID string) error {
	var answer struct {
		OK bool `json:"ok"`
	}
	if err := h.post(ctx, "/api/auth/internal/activity-changed",
		map[string]any{"activityId": activityID}, &answer); err != nil {
		return err
	}
	if !answer.OK {
		return fmt.Errorf("activities: the change was not announced")
	}
	return nil
}

// GroupCheck asks /api/auth/internal/visit-group-check (docs/migration/33).
func (h *HTTPPricing) GroupCheck(ctx context.Context, q GroupQuestion) (GroupVerdict, error) {
	var answer struct {
		OK bool `json:"ok"`
		GroupVerdict
	}
	if err := h.post(ctx, "/api/auth/internal/visit-group-check", map[string]any{
		"kind": q.Kind, "activityIds": q.ActivityIDs, "scheduledDate": q.Date, "reason": q.Reason,
		"userId": q.UserID, "role": q.Role,
	}, &answer); err != nil {
		return GroupVerdict{}, err
	}
	if !answer.OK {
		return GroupVerdict{}, fmt.Errorf("activities: the group check was not answered")
	}
	return answer.GroupVerdict, nil
}
