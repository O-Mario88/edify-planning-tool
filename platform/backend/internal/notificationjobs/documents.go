package notificationjobs

// The document_lifecycle job (apps.realtime.jobs._do_document_lifecycle over
// apps.documents.jobs): published documents made effective on their date,
// readable ones expired past their version's expiry, acknowledgement
// reminders 7/3/1/0 days ahead and daily once overdue (once a day each), and
// viewer sessions idle half an hour closed. Retrying a failed preview
// conversion needs the converter, which Go does not run: failed previews are
// left and named in the error.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

const sessionIdle = 30 * time.Minute

// reminderDaysBefore are REMINDER_DAYS_BEFORE.
var reminderDaysBefore = []int{7, 3, 1, 0}

// DocumentLifecycle says how many documents, reminders and sessions it moved.
func DocumentLifecycle(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, push activities.NoticePush) (int, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	day := today.Format(time.DateOnly)
	var failed int
	if err := tx.QueryRow(ctx, `SELECT count(*)::int FROM document_version WHERE preview_status = 'failed'`).Scan(&failed); err != nil {
		return 0, fmt.Errorf("notificationjobs: counting failed previews: %w", err)
	}
	if failed > 0 {
		return 0, fmt.Errorf("notificationjobs: %d failed document previews need the existing application's converter (retry_failed_previews)", failed)
	}
	done := 0
	// activate_effective_documents
	tag, err := tx.Exec(ctx, `UPDATE document_asset d SET status = 'effective', updated_at = $2
FROM document_version v WHERE v.id = d.current_version_id AND d.status = 'published'
  AND v.effective_date IS NOT NULL AND v.effective_date <= $1::date`, day, now)
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: making documents effective: %w", err)
	}
	done += int(tag.RowsAffected())
	// expire_documents
	tag, err = tx.Exec(ctx, `UPDATE document_asset d SET status = 'expired', updated_at = $2
FROM document_version v WHERE v.id = d.current_version_id AND d.status IN ('published', 'effective')
  AND v.expiry_date IS NOT NULL AND v.expiry_date < $1::date`, day, now)
	if err != nil {
		return done, fmt.Errorf("notificationjobs: expiring documents: %w", err)
	}
	done += int(tag.RowsAffected())
	sent, err := acknowledgementReminders(ctx, tx, today, now, kampala, push)
	done += sent
	if err != nil {
		return done, err
	}
	// finalise_engagement_sessions
	tag, err = tx.Exec(ctx, `UPDATE document_engagement_session SET finalised = true, updated_at = $2
WHERE NOT finalised AND last_heartbeat_at < $1`, now.Add(-sessionIdle), now)
	if err != nil {
		return done, fmt.Errorf("notificationjobs: closing idle viewer sessions: %w", err)
	}
	return done + int(tag.RowsAffected()), nil
}

type pendingAck struct {
	id, user, title, reason string
	due                     time.Time
	reminded                *time.Time
}

// acknowledgementReminders is send_acknowledgement_reminders.
func acknowledgementReminders(ctx context.Context, tx pgx.Tx, today, now time.Time, kampala *time.Location,
	push activities.NoticePush) (int, error) {
	rows, err := tx.Query(ctx, `SELECT a.id, a.user_id, d.title, d.acknowledgement_reason, a.due_date, a.last_reminded_at
FROM document_acknowledgement a JOIN document_asset d ON d.id = a.document_id
WHERE a.state = 'pending' AND a.due_date IS NOT NULL ORDER BY a.created_at DESC`)
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: reading the pending acknowledgements: %w", err)
	}
	pending, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (pendingAck, error) {
		var a pendingAck
		err := row.Scan(&a.id, &a.user, &a.title, &a.reason, &a.due, &a.reminded)
		return a, err
	})
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: reading the pending acknowledgements: %w", err)
	}
	sent := 0
	for _, a := range pending {
		left := days(a.due, today)
		overdue := left < 0
		if !overdue && !inInts(reminderDaysBefore, left) {
			continue
		}
		if a.reminded != nil {
			r := a.reminded.In(kampala)
			if time.Date(r.Year(), r.Month(), r.Day(), 0, 0, 0, 0, time.UTC).Equal(today) {
				continue
			}
		}
		event, title, priority := "documents.acknowledgement_due", "", "normal"
		switch {
		case overdue:
			event, title = "documents.acknowledgement_overdue", "Overdue: "+a.title
		case left == 0:
			title = "Due today: " + a.title
		default:
			title = fmt.Sprintf("Due in %d days: %s", left, a.title)
		}
		if overdue || left <= 1 {
			priority = "high"
		}
		body := a.reason
		if body == "" {
			body = "This document is waiting for your response."
		}
		if _, err := activities.NotifyInTx(ctx, tx, push, slog.Default(), now, a.id, activities.Notice{
			Title: title, Body: body, Event: event, Category: "policy", ContextType: "document_acknowledgement",
			Priority: priority,
		}, []activities.NoticeTo{{UserID: a.user, Route: "/dashboard", Label: "View Dashboard"}}); err != nil {
			return sent, fmt.Errorf("notificationjobs: sending the acknowledgement reminder: %w", err)
		}
		if _, err := tx.Exec(ctx, `UPDATE document_acknowledgement SET reminder_count = reminder_count + 1,
  last_reminded_at = $2, updated_at = $2 WHERE id = $1`, a.id, now); err != nil {
			return sent, fmt.Errorf("notificationjobs: recording the reminder: %w", err)
		}
		sent++
	}
	return sent, nil
}

func inInts(list []int, v int) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
