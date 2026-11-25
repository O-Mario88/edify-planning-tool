package activities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// PersonNotice is notifications.services.notify_from_person's arguments: a
// notice one person sends another (a Follow Up, a reminder, a return),
// looked up by recipient, context and event, with the fields to write.
type PersonNotice struct {
	Recipient, ContextType, ContextID, Event string
	// Sender is the person sending it; empty for the platform's own notice
	// (update_or_create without a sender).
	Sender string
	// Fields are the defaults, by column: only those notify_from_person
	// allows (recipient_role, title, body, category, target_route,
	// action_label, action_required, priority, status, source_event_id,
	// read_at, resolved_at). A nil value writes NULL.
	Fields map[string]any
}

// ErrPhoneCopy is a phone copy that could not be queued: the notice and its
// email copy stand (the copy runs in a savepoint of its own), and the caller
// logs it and carries on, as _push_on_save does.
var ErrPhoneCopy = errors.New("activities: the notice's phone copy was not queued")

// NotifyFromPerson writes the notice in tx as notify_from_person does, then
// what the save signals add: the email copy (_email_on_save) and, for a new
// notice or a person's reminder that is unread and open, the phone copy
// (_push_on_save). It answers the notice and whether it was new.
func NotifyFromPerson(ctx context.Context, tx pgx.Tx, push NoticePush, now time.Time, n PersonNotice) (string, bool, error) {
	fields, err := json.Marshal(n.Fields)
	if err != nil {
		return "", false, fmt.Errorf("activities: the notice's fields: %w", err)
	}
	var id string
	var created, reminded bool
	if err := tx.QueryRow(ctx, `SELECT out_notification_id, out_created, out_reminded
  FROM gateway_notifications.notify_from_person($1, $2, $3, $4, $5, $6, $7::jsonb, $8)`,
		cuid.New(), n.Recipient, n.ContextType, n.ContextID, n.Event, n.Sender, string(fields), now).Scan(&id, &created, &reminded); err != nil {
		return "", false, fmt.Errorf("activities: sending the person's notice: %w", err)
	}
	if err := QueueEmailCopy(ctx, tx, id, created, reminded, now); err != nil {
		return "", false, err
	}
	if push == nil || !(created || reminded) {
		return id, created, nil
	}
	var unread bool
	if err := tx.QueryRow(ctx, `SELECT status = 'unread' AND resolved_at IS NULL FROM notification WHERE id = $1`, id).Scan(&unread); err != nil {
		return "", false, fmt.Errorf("activities: reading the notice back: %w", err)
	}
	if unread {
		if err := push(ctx, tx, id, n.Recipient, now); err != nil {
			return id, created, fmt.Errorf("%w: %w", ErrPhoneCopy, err)
		}
	}
	return id, created, nil
}
