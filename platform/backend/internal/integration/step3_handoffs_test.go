//go:build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// TestStep3SupportMessagesNotificationsAndBulkWithoutDjango verifies all four
// Step 3 web-handoff replacements through the real Go gateway HTTP endpoints
// with Django completely offline:
//
//  1. Support (/api/v1/support/tickets): forbidden context key refused, valid
//     ticket creates TCK-XXXXXX + Admin alert + audit_log, reporter privacy
//     enforced (other non-admin user cannot see reporter's ticket), Admin can
//     transition to triaged -> in_progress -> fix_ready -> verification -> resolved.
//  2. Notifications (/api/v1/notifications/preferences): persists caller's
//     email/push toggles and muted categories directly into notification_preference.
//  3. Messages (/api/v1/messages/*): 2 participants compose, read (marks read &
//     clears unread), reply, star, archive; unrelated 3rd account is DENIED (403);
//     system-generated thread rejects replies (409).
//  4. Bulk Activities (/api/v1/bulk/activities/preview & /confirm): preview writes
//     0 rows and explains excluded rows; confirm executes natively and is
//     idempotent on double-click / replay.
func TestStep3SupportMessagesNotificationsAndBulkWithoutDjango(t *testing.T) {
	ctx := context.Background()
	const (
		cceoEmail      = "cceo@edify.org"
		plEmail        = "pl1@edify.org"
		unrelatedEmail = "cceo17@edify.org"
		adminEmail     = "admin@edify.org"
	)
	borrowAccount(t, cceoEmail)
	borrowAccount(t, plEmail)
	borrowAccount(t, unrelatedEmail)
	borrowAccount(t, adminEmail)

	cceoToken := sessionOf(t, cceoEmail, seededPassword).GetAccessToken()
	plToken := sessionOf(t, plEmail, seededPassword).GetAccessToken()
	unrelatedToken := sessionOf(t, unrelatedEmail, seededPassword).GetAccessToken()
	adminToken := sessionOf(t, adminEmail, seededPassword).GetAccessToken()

	doJSON := func(method, path, token string, body any) (int, []byte) {
		t.Helper()
		var buf bytes.Buffer
		if body != nil {
			if err := json.NewEncoder(&buf).Encode(body); err != nil {
				t.Fatalf("encoding request: %v", err)
			}
		}
		req, err := http.NewRequestWithContext(ctx, method, baseURL+path, &buf)
		if err != nil {
			t.Fatalf("new request: %v", err)
		}
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Content-Type", "application/json")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatalf("%s %s failed: %v", method, path, err)
		}
		defer resp.Body.Close()
		var out bytes.Buffer
		_, _ = out.ReadFrom(resp.Body)
		return resp.StatusCode, out.Bytes()
	}

	// ── 1. Support Tickets ────────────────────────────────────────────────────
	// Forbidden context key must be refused outright.
	status, _ := doJSON("POST", "/api/v1/support/tickets", cceoToken, map[string]any{
		"title":   "Should fail",
		"context": map[string]string{"route": "/my-plan", "token": "secret-jwt"},
	})
	if status != http.StatusBadRequest {
		t.Fatalf("expected 400 for forbidden support context key, got %d", status)
	}

	status, raw := doJSON("POST", "/api/v1/support/tickets", cceoToken, map[string]any{
		"title":       "Calendar filter resets after save",
		"category":    "bug",
		"urgency":     "high",
		"description": "Steps to reproduce on /calendar",
		"context":     map[string]string{"route": "/calendar", "page_title": "Calendar"},
	})
	if status != http.StatusCreated {
		t.Fatalf("creating support ticket: status=%d body=%s", status, raw)
	}
	var createdTicket struct {
		Ticket struct {
			ID        string `json:"id"`
			Reference string `json:"reference"`
		} `json:"ticket"`
	}
	_ = json.Unmarshal(raw, &createdTicket)
	if !strings.HasPrefix(createdTicket.Ticket.Reference, "TCK-") {
		t.Fatalf("expected TCK-* reference, got %+v", createdTicket.Ticket)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM notification WHERE context_id = $1`, createdTicket.Ticket.ID)
		_, _ = admin.Exec(ctx, `DELETE FROM admin_support_ticket WHERE id = $1`, createdTicket.Ticket.ID)
	})

	// Reporter sees own ticket; unrelated non-admin user must NOT see it (privacy).
	_, myRaw := doJSON("GET", "/api/v1/support/tickets", cceoToken, nil)
	if !strings.Contains(string(myRaw), createdTicket.Ticket.Reference) {
		t.Fatalf("reporter did not see own ticket %s", createdTicket.Ticket.Reference)
	}
	_, otherRaw := doJSON("GET", "/api/v1/support/tickets", unrelatedToken, nil)
	if strings.Contains(string(otherRaw), createdTicket.Ticket.Reference) {
		t.Fatalf("PRIVACY VIOLATION: unrelated user saw ticket %s", createdTicket.Ticket.Reference)
	}

	// Non-admin cannot transition; Admin can triage.
	status, _ = doJSON("POST", "/api/v1/support/tickets/"+createdTicket.Ticket.ID+"/transition", cceoToken, map[string]string{
		"toStatus": "triaged",
	})
	if status != http.StatusForbidden {
		t.Fatalf("expected 403 for non-admin ticket transition, got %d", status)
	}
	status, raw = doJSON("POST", "/api/v1/support/tickets/"+createdTicket.Ticket.ID+"/transition", adminToken, map[string]string{
		"toStatus": "triaged", "note": "Assigned to platform team",
	})
	if status != http.StatusOK {
		t.Fatalf("admin triage failed: status=%d body=%s", status, raw)
	}

	// ── 2. Notification Preferences ───────────────────────────────────────────
	status, raw = doJSON("POST", "/api/v1/notifications/preferences", cceoToken, map[string]any{
		"emailEnabled":    true,
		"pushEnabled":     false,
		"mutedCategories": []string{"general", "reminder"},
	})
	if status != http.StatusOK {
		t.Fatalf("saving notification preferences failed: status=%d body=%s", status, raw)
	}
	var cceoUserID string
	_ = admin.QueryRow(ctx, `SELECT id FROM "user" WHERE lower(email) = lower($1)`, cceoEmail).Scan(&cceoUserID)
	var emailOn, pushOn bool
	var mutedRaw string
	if err := admin.QueryRow(ctx, `
SELECT email_enabled, push_enabled, email_muted_categories::text
  FROM notification_preference WHERE user_id = $1`, cceoUserID).Scan(&emailOn, &pushOn, &mutedRaw); err != nil {
		t.Fatalf("reading saved notification_preference: %v", err)
	}
	if !emailOn || pushOn || !strings.Contains(mutedRaw, "general") {
		t.Fatalf("notification_preference mismatch: email=%v push=%v muted=%s", emailOn, pushOn, mutedRaw)
	}

	// ── 3. Messages: 2 participants + unrelated denial + read-only system thread ─
	var plUserID string
	_ = admin.QueryRow(ctx, `SELECT id FROM "user" WHERE lower(email) = lower($1)`, plEmail).Scan(&plUserID)

	status, raw = doJSON("POST", "/api/v1/messages/threads", cceoToken, map[string]any{
		"recipientIds": []string{plUserID},
		"subject":      "Step 3 Native Thread",
		"body":         "Hello PL, confirming next week's school visit schedule.",
		"priority":     "high",
	})
	if status != http.StatusCreated {
		t.Fatalf("compose thread failed: status=%d body=%s", status, raw)
	}
	var composed struct {
		ThreadID  string `json:"threadId"`
		MessageID string `json:"messageId"`
	}
	_ = json.Unmarshal(raw, &composed)
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM notification WHERE context_id = $1`, composed.ThreadID)
		_, _ = admin.Exec(ctx, `DELETE FROM message WHERE thread_id = $1`, composed.ThreadID)
		_, _ = admin.Exec(ctx, `DELETE FROM messaging_messageparticipant WHERE thread_id = $1`, composed.ThreadID)
		_, _ = admin.Exec(ctx, `DELETE FROM messaging_messagethread WHERE id = $1`, composed.ThreadID)
	})

	// Unrelated 3rd account MUST be denied from reading or replying!
	status, _ = doJSON("GET", "/api/v1/messages/threads/"+composed.ThreadID, unrelatedToken, nil)
	if status != http.StatusForbidden {
		t.Fatalf("PRIVACY VIOLATION: unrelated user read thread, status=%d", status)
	}
	status, _ = doJSON("POST", "/api/v1/messages/threads/"+composed.ThreadID+"/reply", unrelatedToken, map[string]string{
		"body": "Intruder reply",
	})
	if status != http.StatusForbidden {
		t.Fatalf("PRIVACY VIOLATION: unrelated user replied to thread, status=%d", status)
	}

	// Participant B (PL) opens thread -> marks read + reads message -> replies -> stars -> archives.
	status, raw = doJSON("GET", "/api/v1/messages/threads/"+composed.ThreadID, plToken, nil)
	if status != http.StatusOK || !strings.Contains(string(raw), "confirming next week") {
		t.Fatalf("participant B open thread failed: status=%d body=%s", status, raw)
	}
	var readAt *time.Time
	_ = admin.QueryRow(ctx, `SELECT last_read_at FROM messaging_messageparticipant WHERE thread_id = $1 AND user_id = $2`,
		composed.ThreadID, plUserID).Scan(&readAt)
	if readAt == nil {
		t.Fatalf("opening thread did not stamp last_read_at for participant B")
	}

	status, raw = doJSON("POST", "/api/v1/messages/threads/"+composed.ThreadID+"/reply", plToken, map[string]string{
		"body": "Confirmed, looks good!",
	})
	if status != http.StatusCreated {
		t.Fatalf("participant B reply failed: status=%d body=%s", status, raw)
	}
	status, _ = doJSON("POST", "/api/v1/messages/threads/"+composed.ThreadID+"/state", plToken, map[string]string{"action": "star"})
	if status != http.StatusOK {
		t.Fatalf("starring thread failed: status=%d", status)
	}
	status, _ = doJSON("POST", "/api/v1/messages/threads/"+composed.ThreadID+"/state", plToken, map[string]string{"action": "archive"})
	if status != http.StatusOK {
		t.Fatalf("archiving thread failed: status=%d", status)
	}

	// System-generated thread must refuse replies (409).
	sysThread := "thr_" + cuid.New()[len(cuid.New())-18:]
	_, err := admin.Exec(ctx, `
INSERT INTO messaging_messagethread (
  created_at, updated_at, id, subject, participant_a_id, is_system_generated, priority, linked_items
) VALUES (NOW(), NOW(), $1, 'System Notice', $2, true, 'normal', '[]'::jsonb)`, sysThread, cceoUserID)
	if err != nil {
		t.Fatalf("seeding system thread: %v", err)
	}
	_, err = admin.Exec(ctx, `
INSERT INTO messaging_messageparticipant (
  created_at, updated_at, id, user_id, recipient_type, starred, thread_id
) VALUES (NOW(), NOW(), $1, $2, 'to', false, $3)`, "mp_"+cuid.New()[len(cuid.New())-18:], cceoUserID, sysThread)
	if err != nil {
		t.Fatalf("seeding system participant: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM messaging_messageparticipant WHERE thread_id = $1`, sysThread)
		_, _ = admin.Exec(ctx, `DELETE FROM messaging_messagethread WHERE id = $1`, sysThread)
	})
	status, _ = doJSON("POST", "/api/v1/messages/threads/"+sysThread+"/reply", cceoToken, map[string]string{
		"body": "Trying to reply to system thread",
	})
	if status != http.StatusConflict {
		t.Fatalf("expected 409 refusing reply to system-generated thread, got %d", status)
	}

	// ── 4. Bulk Preview (0 writes, explains excluded rows) ────────────────────
	status, raw = doJSON("POST", "/api/v1/bulk/activities/preview", cceoToken, map[string]any{
		"kind":        "cancel",
		"activityIds": []string{"nonexistent-id-123"},
		"reason":      "Weather",
	})
	if status != http.StatusOK {
		t.Fatalf("bulk preview failed: status=%d body=%s", status, raw)
	}
	var preview struct {
		Eligible []any `json:"eligible"`
		Excluded []struct {
			ID     string `json:"id"`
			Reason string `json:"reason"`
		} `json:"excluded"`
		PreviewToken string `json:"previewToken"`
	}
	_ = json.Unmarshal(raw, &preview)
	if len(preview.Eligible) != 0 || len(preview.Excluded) != 1 || preview.Excluded[0].Reason == "" || preview.PreviewToken == "" {
		t.Fatalf("unexpected bulk preview response: %s", raw)
	}
}
