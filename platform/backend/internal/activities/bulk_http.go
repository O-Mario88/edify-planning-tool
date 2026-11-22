package activities

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// BulkPreviewItem explains whether a ticked activity is eligible or why it is
// excluded — computed with ZERO database writes.
type BulkPreviewItem struct {
	ID       string `json:"id"`
	Title    string `json:"title"`
	Where    string `json:"where"`
	Day      string `json:"day"`
	Eligible bool   `json:"eligible"`
	Reason   string `json:"reason,omitempty"`
}

// BulkPreviewResponse is returned by POST /api/v1/bulk/activities/preview.
type BulkPreviewResponse struct {
	Kind         string            `json:"kind"`
	Eligible     []BulkPreviewItem `json:"eligible"`
	Excluded     []BulkPreviewItem `json:"excluded"`
	PreviewToken string            `json:"previewToken"`
}

// BulkConfirmResponse is returned by POST /api/v1/bulk/activities/confirm.
type BulkConfirmResponse struct {
	Done     []GroupPick `json:"done"`
	Refused  []GroupPick `json:"refused"`
	Message  string      `json:"message"`
	Outcome  string      `json:"outcome,omitempty"`
	Replayed bool        `json:"replayed,omitempty"`
}

type bulkConfirmCacheEntry struct {
	response BulkConfirmResponse
	storedAt time.Time
}

// BulkHTTPHandler exposes native Go two-step bulk preview (0 writes) and
// idempotent confirm (rechecks eligibility + stale-preview safe) endpoints,
// removing the SelectionBar.tsx handoff to Django.
type BulkHTTPHandler struct {
	svc   *Service
	mu    sync.Mutex
	cache map[string]bulkConfirmCacheEntry
}

// NewBulkHTTPHandler constructs a native Go bulk activity preview/confirm handler.
func NewBulkHTTPHandler(svc *Service) *BulkHTTPHandler {
	return &BulkHTTPHandler{
		svc:   svc,
		cache: map[string]bulkConfirmCacheEntry{},
	}
}

func previewDigest(userID, kind, dateStr string, ids []string) string {
	sum := sha256.Sum256([]byte(userID + "|" + kind + "|" + dateStr + "|" + strings.Join(ids, ",")))
	return hex.EncodeToString(sum[:16])
}

// Preview evaluates every ticked activity with ZERO writes and explains every
// excluded row.
func (h *BulkHTTPHandler) Preview(ctx context.Context, p auth.Principal, kind string, rawIDs []string, dateStr, reason string) (BulkPreviewResponse, error) {
	ids, err := groupIDs(rawIDs)
	if err != nil {
		return BulkPreviewResponse{}, err
	}
	if kind != "reschedule" && kind != "cancel" {
		return BulkPreviewResponse{}, refuse("Unsupported bulk action %q.", kind)
	}
	var allowedStatuses []string
	if kind == "reschedule" {
		allowedStatuses = movableStatuses
	} else {
		allowedStatuses = cancellableStatuses
	}

	var eligible, excluded []BulkPreviewItem
	for _, id := range ids {
		var title, where, status, responsible, payment string
		var planned *time.Time
		err := h.svc.db.QueryRow(ctx, `
SELECT COALESCE(NULLIF(a.activity_name_snapshot, ''), a.activity_type),
       COALESCE(s.name, c.name, ''),
       a.status, COALESCE(a.responsible_staff_id, ''), COALESCE(a.payment_status, 'none'),
       a.planned_date
  FROM activity a
  LEFT JOIN school s ON s.id = a.school_id
  LEFT JOIN cluster c ON c.id = a.cluster_id
 WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(&title, &where, &status, &responsible, &payment, &planned)
		if err != nil {
			excluded = append(excluded, BulkPreviewItem{ID: id, Eligible: false, Reason: "Activity not found."})
			continue
		}
		dayStr := ""
		if planned != nil {
			dayStr = planned.Format(time.DateOnly)
		}
		item := BulkPreviewItem{ID: id, Title: title, Where: where, Day: dayStr}
		switch {
		case p.StaffProfileID == "" || responsible != p.StaffProfileID:
			item.Reason = "Owned by another staff member."
			excluded = append(excluded, item)
		case payment == "disbursed" || payment == "paid":
			item.Reason = "Already has disbursed or paid funds."
			excluded = append(excluded, item)
		case !in(allowedStatuses, status):
			item.Reason = fmt.Sprintf("Cannot %s an activity in status %q.", kind, status)
			excluded = append(excluded, item)
		case kind == "reschedule" && dateStr != "" && dayStr == strings.TrimSpace(dateStr):
			item.Reason = groupAlreadyOnDay
			excluded = append(excluded, item)
		case kind == "cancel" && status == "cancelled":
			item.Reason = groupAlreadyOff
			excluded = append(excluded, item)
		default:
			// Also run live pricing check (read-only) so locked weeks explain exclusion upfront.
			if kind == "reschedule" && dateStr != "" {
				if mp, ok := h.svc.pricing.(MovePricing); ok {
					mv, mErr := mp.MoveCheck(ctx, id, strings.TrimSpace(dateStr), reason)
					if mErr == nil && (mv.Refusal != "" || mv.LeftFrozen || mv.TakesBack) {
						item.Reason = mv.Refusal
						if item.Reason == "" {
							item.Reason = "This activity's week has left draft status."
						}
						excluded = append(excluded, item)
						continue
					}
				}
			} else if kind == "cancel" {
				if cp, ok := h.svc.pricing.(CancelPricing); ok {
					cv, cErr := cp.CancelCheck(ctx, id, reason)
					if cErr == nil && (cv.Refusal != "" || cv.FrozenWeeks || cv.Credited) {
						item.Reason = cv.Refusal
						if item.Reason == "" {
							item.Reason = "This activity has locked finance or milestone records."
						}
						excluded = append(excluded, item)
						continue
					}
				}
			}
			item.Eligible = true
			eligible = append(eligible, item)
		}
	}
	if eligible == nil {
		eligible = []BulkPreviewItem{}
	}
	if excluded == nil {
		excluded = []BulkPreviewItem{}
	}
	return BulkPreviewResponse{
		Kind:         kind,
		Eligible:     eligible,
		Excluded:     excluded,
		PreviewToken: previewDigest(p.UserID, kind, strings.TrimSpace(dateStr), ids),
	}, nil
}

// Confirm rechecks eligibility, prevents double-click / replay duplicates via
// idempotencyKey, and executes GroupReschedule or GroupCancel natively in Go.
func (h *BulkHTTPHandler) Confirm(
	ctx context.Context, p auth.Principal, kind string, ids []string, dateStr, reason, idempotencyKey string, origin Origin,
) (BulkConfirmResponse, error) {
	cacheKey := ""
	if strings.TrimSpace(idempotencyKey) != "" {
		cacheKey = p.UserID + ":" + strings.TrimSpace(idempotencyKey)
		h.mu.Lock()
		if hit, ok := h.cache[cacheKey]; ok && time.Since(hit.storedAt) < 10*time.Minute {
			h.mu.Unlock()
			resp := hit.response
			resp.Replayed = true
			return resp, nil
		}
		h.mu.Unlock()
	}

	req := GroupRequest{ActivityIDs: ids, Date: strings.TrimSpace(dateStr), Reason: strings.TrimSpace(reason)}
	var ans GroupAnswer
	var err error
	switch kind {
	case "reschedule":
		ans, err = h.svc.GroupReschedule(ctx, p, req, origin)
	case "cancel":
		ans, err = h.svc.GroupCancel(ctx, p, req, origin)
	default:
		return BulkConfirmResponse{}, refuse("Unsupported bulk action %q.", kind)
	}
	if err != nil {
		return BulkConfirmResponse{}, err
	}
	out := BulkConfirmResponse{
		Done:    ans.Done,
		Refused: ans.Refused,
		Message: ans.Message,
		Outcome: ans.Outcome,
	}
	if out.Done == nil {
		out.Done = []GroupPick{}
	}
	if out.Refused == nil {
		out.Refused = []GroupPick{}
	}
	if cacheKey != "" {
		h.mu.Lock()
		h.cache[cacheKey] = bulkConfirmCacheEntry{response: out, storedAt: time.Now()}
		h.mu.Unlock()
	}
	return out, nil
}

// Register mounts POST /api/v1/bulk/activities/preview and /confirm on mux.
func (h *BulkHTTPHandler) Register(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("POST /api/v1/bulk/activities/preview", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeBulkJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		var in struct {
			Kind        string   `json:"kind"`
			ActivityIDs []string `json:"activityIds"`
			Date        string   `json:"date"`
			Reason      string   `json:"reason"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<18)).Decode(&in); err != nil {
			writeBulkJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		resp, err := h.Preview(r.Context(), p, in.Kind, in.ActivityIDs, in.Date, in.Reason)
		if err != nil {
			writeBulkErr(w, err)
			return
		}
		writeBulkJSON(w, http.StatusOK, resp)
	})

	mux.HandleFunc("POST /api/v1/bulk/activities/confirm", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeBulkJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		var in struct {
			Kind           string   `json:"kind"`
			ActivityIDs    []string `json:"activityIds"`
			Date           string   `json:"date"`
			Reason         string   `json:"reason"`
			IdempotencyKey string   `json:"idempotencyKey"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<18)).Decode(&in); err != nil {
			writeBulkJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		origin := Origin{UserAgent: r.Header.Get("User-Agent")}
		resp, err := h.Confirm(r.Context(), p, in.Kind, in.ActivityIDs, in.Date, in.Reason, in.IdempotencyKey, origin)
		if err != nil {
			writeBulkErr(w, err)
			return
		}
		writeBulkJSON(w, http.StatusOK, resp)
	})
}

func writeBulkErr(w http.ResponseWriter, err error) {
	var ref *Refusal
	if errors.As(err, &ref) {
		writeBulkJSON(w, http.StatusBadRequest, map[string]string{"error": ref.Message})
		return
	}
	if errors.Is(err, ErrHandOn) {
		writeBulkJSON(w, http.StatusConflict, map[string]string{"error": "One or more selected activities changed or cannot be bulk-updated together; refresh and preview again."})
		return
	}
	writeBulkJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
}

func writeBulkJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
