// Package workflowmsg is apps.messaging.services.workflow_message: the
// system-written thread about one record (a school, a hand-over), found or
// started, its recipients made participants, the new message added, and each
// recipient told in their bell that a message came. It is best-effort, as the
// existing one is: a failure is logged and the save it belongs to stands.
package workflowmsg

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// Message is workflow_message's arguments.
type Message struct {
	ContextType, ContextID string
	// Label is the thread's context label as resolve_context_record words
	// it for the context (for a "School" or "PartnerAssignment" context,
	// which it does not look up, "<type> <id>").
	Label         string
	Subject, Body string
	Recipients    []string
	Category      string
	Priority      string
	// Sender is the person whose save this is; empty for the platform.
	Sender string
}

// FallbackLabel is resolve_context_record's label for a context type it does
// not look up and has no tab for: the type and the id.
func FallbackLabel(contextType, contextID string) string { return contextType + " " + contextID }

// previewLimit is _notify_recipient's 120-character preview.
const previewLimit = 120

// Post writes m in tx under a savepoint; a failure rolls back only the
// message and is logged, as workflow_message's own try does. It answers who
// was told, for the caller's live events once the save commits.
func Post(ctx context.Context, tx pgx.Tx, push activities.NoticePush, logger *slog.Logger, now time.Time, m Message) []string {
	if logger == nil {
		logger = slog.Default()
	}
	inner, err := tx.Begin(ctx)
	if err != nil {
		logger.ErrorContext(ctx, "workflowmsg: could not create workflow message", "context", m.ContextType, "id", m.ContextID, "err", err)
		return nil
	}
	told, err := post(ctx, inner, push, logger, now, m)
	if err == nil {
		err = inner.Commit(ctx)
	}
	if err != nil {
		_ = inner.Rollback(ctx)
		logger.ErrorContext(ctx, "workflowmsg: could not create workflow message", "context", m.ContextType, "id", m.ContextID, "err", err)
		return nil
	}
	return told
}

func post(ctx context.Context, tx pgx.Tx, push activities.NoticePush, logger *slog.Logger, now time.Time, m Message) ([]string, error) {
	priority := m.Priority
	if priority == "" {
		priority = "normal"
	}
	var thread string
	err := tx.QueryRow(ctx, `SELECT id FROM messaging_messagethread
WHERE context_type = $1 AND context_id = $2 AND is_system_generated ORDER BY id LIMIT 1`,
		m.ContextType, m.ContextID).Scan(&thread)
	if errors.Is(err, pgx.ErrNoRows) {
		thread = cuid.New()
		_, err = tx.Exec(ctx, `INSERT INTO messaging_messagethread (created_at, updated_at, id, subject, context_type, context_id,
  context_label, category, priority, created_by, last_reply_at, is_system_generated, linked_items, participant_a_id, participant_b_id)
VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, $9, NULL, true, '[]'::jsonb, NULL, NULL)`,
			now, thread, m.Subject, m.ContextType, m.ContextID, m.Label, nilIfEmpty(m.Category), priority, nilIfEmpty(m.Sender))
	}
	if err != nil {
		return nil, fmt.Errorf("workflowmsg: the thread: %w", err)
	}
	distinct := unique(m.Recipients)
	for _, id := range distinct {
		if _, err := tx.Exec(ctx, `INSERT INTO messaging_messageparticipant (created_at, updated_at, id, user_id, recipient_type,
  last_read_at, archived_at, starred, thread_id)
VALUES ($1, $1, $2, $3, 'to', NULL, NULL, false, $4) ON CONFLICT (thread_id, user_id) DO NOTHING`,
			now, cuid.New(), id, thread); err != nil {
			return nil, fmt.Errorf("workflowmsg: a participant: %w", err)
		}
	}
	var first any
	if len(m.Recipients) > 0 {
		first = m.Recipients[0]
	}
	sender := m.Sender
	if sender == "" {
		sender = "system"
	}
	message := cuid.New()
	if _, err := tx.Exec(ctx, `INSERT INTO message (created_at, updated_at, id, thread_id, sender_id, recipient_id, body, category,
  context_type, context_id, target_route, priority, action_required, is_system_generated, status)
VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, $9, NULL, $10, false, true, 'unread')`,
		now, message, thread, sender, first, m.Body, nilIfEmpty(m.Category), m.ContextType, m.ContextID, priority); err != nil {
		return nil, fmt.Errorf("workflowmsg: the message: %w", err)
	}
	if _, err := tx.Exec(ctx, `UPDATE messaging_messagethread SET last_reply_at = $2, updated_at = $2 WHERE id = $1`, thread, now); err != nil {
		return nil, fmt.Errorf("workflowmsg: the thread's last reply: %w", err)
	}
	to := []activities.NoticeTo{}
	for _, id := range distinct {
		if id != m.Sender {
			to = append(to, activities.NoticeTo{UserID: id, Route: "/messages/" + message, Label: "Open Chat"})
		}
	}
	if len(to) == 0 {
		return nil, nil
	}
	// _notify_recipient's own try: a bell that cannot be rung leaves the
	// message standing.
	bell, err := tx.Begin(ctx)
	if err != nil {
		return nil, nil
	}
	told, err := activities.NotifyInTx(ctx, bell, push, logger, now, message, activities.Notice{
		Title: "New message from Edify Workflow", Body: Preview(m.Body), Event: "message", Category: "messages",
		ContextType: "Message", Priority: priority,
	}, to)
	if err == nil {
		err = bell.Commit(ctx)
	}
	if err != nil {
		_ = bell.Rollback(ctx)
		logger.WarnContext(ctx, "workflowmsg: the message's notices were not sent", "message", message, "err", err)
		return nil, nil
	}
	return told, nil
}

// Preview is _notify_recipient's preview: the body trimmed, cut to 117
// characters and an ellipsis past 120.
func Preview(body string) string {
	r := []rune(pyStrip(body))
	if len(r) > previewLimit {
		return string(r[:previewLimit-3]) + "…"
	}
	return string(r)
}

// pyStrip is str.strip(): Python's whitespace from both ends.
func pyStrip(s string) string {
	isSpace := func(r rune) bool {
		switch r {
		case ' ', '\t', '\n', '\r', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x1f, 0x85, 0xa0, 0x1680, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000:
			return true
		}
		return r >= 0x2000 && r <= 0x200a
	}
	r := []rune(s)
	start, end := 0, len(r)
	for start < end && isSpace(r[start]) {
		start++
	}
	for end > start && isSpace(r[end-1]) {
		end--
	}
	return string(r[start:end])
}

// unique is {r for r in recipient_ids if r}: each id once, none empty, in
// the order given.
func unique(ids []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, id := range ids {
		if id != "" && !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out
}

func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}
