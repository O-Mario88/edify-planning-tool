// Package notifymail is the outbox's `notification.email` handler
// (apps.notifications.email_delivery.handle_email): one queued email copy of
// a notification, sent through the configured provider (Resend) or recorded
// as not sent and why. It runs outside any transaction, as the existing
// handler does (atomic=False): each step is recorded as it happens, so a copy
// left "sending" by a worker that died is sent again with the same provider
// idempotency key, which the provider sends once.
package notifymail

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	maxAttempts  = 6 // MAX_ATTEMPTS
	lastErrorMax = 255

	statusSending        = "sending"
	statusRetryScheduled = "retry_scheduled"
	statusAccepted       = "accepted"
	statusFailed         = "failed"
	statusSkipped        = "skipped"
	statusNotConfigured  = "not_configured"

	resolvedFirst  = "The work was done before the email was sent."
	readFirst      = "Read in the app before the email was sent."
	noProvider     = "No email provider is set up, so nothing was sent."
	noRecipient    = "The recipient has no active account with an email address."
	unavailableErr = "EmailUnavailable"
)

// sendable are _SENDABLE.
var sendable = []string{"queued", statusRetryScheduled, statusSending}

// Mailer sends one message; it is the existing MailerService.deliver.
type Mailer interface {
	Configured() bool
	Deliver(ctx context.Context, m Message, idempotencyKey string) Result
}

// Handler is the email handler with its provider and clock zone.
type Handler struct {
	Mailer  Mailer
	BaseURL string
	Kampala *time.Location
}

// delivery is the copy's row.
type delivery struct {
	id, notificationID, recipientID, status string
	attempts                                int
}

// Handle is handle_email for one payload.
func (h Handler) Handle(ctx context.Context, pool *pgxpool.Pool, payload map[string]any, now time.Time) error {
	id, _ := payload["deliveryId"].(string)
	d, ok, err := readDelivery(ctx, pool, id)
	if err != nil || !ok || !in(d.status, sendable) {
		return err
	}
	n, ok, err := readNotification(ctx, pool, d.notificationID)
	if err != nil {
		return err
	}
	if !ok || n.resolved {
		return record(ctx, pool, d.id, statusSkipped, now, withError(resolvedFirst))
	}
	if n.status != "unread" {
		return record(ctx, pool, d.id, statusSkipped, now, withError(readFirst))
	}
	if h.Mailer == nil || !h.Mailer.Configured() {
		return record(ctx, pool, d.id, statusNotConfigured, now, withError(noProvider))
	}
	to, ok, err := readRecipient(ctx, pool, d.recipientID)
	if err != nil {
		return err
	}
	if !ok {
		return record(ctx, pool, d.id, statusSkipped, now, withError(noRecipient))
	}
	attempts := d.attempts + 1
	if err := record(ctx, pool, d.id, statusSending, now, withAttempts(attempts)); err != nil {
		return err
	}
	message, err := h.compose(ctx, pool, n, to)
	if err != nil {
		return err
	}
	result := h.Mailer.Deliver(ctx, message, "edify-notification-"+d.id)
	if result.Accepted {
		return record(ctx, pool, d.id, statusAccepted, now, withProvider(result.ProviderID, now))
	}
	if result.Retryable && attempts < maxAttempts {
		if err := record(ctx, pool, d.id, statusRetryScheduled, now, withError(result.Error)); err != nil {
			return err
		}
		return fmt.Errorf("%s: %s", unavailableErr, result.Error)
	}
	return record(ctx, pool, d.id, statusFailed, now, withError(result.Error))
}

func readDelivery(ctx context.Context, q *pgxpool.Pool, id string) (delivery, bool, error) {
	var d delivery
	err := q.QueryRow(ctx, `SELECT id, notification_id, recipient_id, status, attempts FROM notification_delivery
WHERE id = $1 AND channel = 'email'`, id).Scan(&d.id, &d.notificationID, &d.recipientID, &d.status, &d.attempts)
	if errors.Is(err, pgx.ErrNoRows) {
		return d, false, nil
	}
	if err != nil {
		return d, false, fmt.Errorf("notifymail: reading the email copy: %w", err)
	}
	return d, true, nil
}

// notice is the notification the copy is of.
type notice struct {
	id, title, body, category, status, priority string
	actionLabel, senderID                       *string
	actionRequired, resolved                    bool
	sentAt                                      time.Time
}

func readNotification(ctx context.Context, q *pgxpool.Pool, id string) (notice, bool, error) {
	var n notice
	var body *string
	var category *string
	err := q.QueryRow(ctx, `SELECT id, title, body, category, status, priority, action_label, sender_id, action_required,
  resolved_at IS NOT NULL, COALESCE(last_reminded_at, created_at)
FROM notification WHERE id = $1`, id).Scan(&n.id, &n.title, &body, &category, &n.status, &n.priority, &n.actionLabel,
		&n.senderID, &n.actionRequired, &n.resolved, &n.sentAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return n, false, nil
	}
	if err != nil {
		return n, false, fmt.Errorf("notifymail: reading the notification: %w", err)
	}
	if body != nil {
		n.body = *body
	}
	if category != nil {
		n.category = *category
	}
	return n, true, nil
}

// recipient is an active account with an email address.
type recipient struct{ name, email string }

func readRecipient(ctx context.Context, q *pgxpool.Pool, id string) (recipient, bool, error) {
	var r recipient
	var active, deleted bool
	err := q.QueryRow(ctx, `SELECT COALESCE(name, ''), COALESCE(email, ''), is_active, deleted_at IS NOT NULL
FROM "user" WHERE id = $1`, id).Scan(&r.name, &r.email, &active, &deleted)
	if errors.Is(err, pgx.ErrNoRows) {
		return r, false, nil
	}
	if err != nil {
		return r, false, fmt.Errorf("notifymail: reading the recipient: %w", err)
	}
	if !active || deleted || strings.TrimSpace(r.email) == "" {
		return r, false, nil
	}
	return r, true, nil
}

// change is the extra columns one _record call sets.
type change struct {
	attempts   *int
	lastError  *string
	providerID *string
	sentAt     *time.Time
}

func withError(text string) change { return change{lastError: &text} }

func withAttempts(n int) change { return change{attempts: &n} }

func withProvider(id string, at time.Time) change {
	empty := ""
	return change{providerID: &id, sentAt: &at, lastError: &empty}
}

// record is _record: the copy's status and the columns given; a failure
// stamps failed_at, and the error is cut to the column's 255 characters.
func record(ctx context.Context, pool *pgxpool.Pool, id, status string, now time.Time, c change) error {
	var failedAt *time.Time
	if status == statusFailed {
		failedAt = &now
	}
	var lastError *string
	if c.lastError != nil {
		cut := truncate(*c.lastError, lastErrorMax)
		lastError = &cut
	}
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("notifymail: opening the record: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `UPDATE notification_delivery SET status = $2, updated_at = $3,
  attempts = COALESCE($4, attempts), last_error = COALESCE($5, last_error),
  provider_message_id = COALESCE($6, provider_message_id), sent_at = COALESCE($7, sent_at),
  failed_at = COALESCE($8, failed_at)
WHERE id = $1`, id, status, now, c.attempts, lastError, c.providerID, c.sentAt, failedAt); err != nil {
		return fmt.Errorf("notifymail: recording the email copy: %w", err)
	}
	return tx.Commit(ctx)
}

func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n])
}

func in(s string, set []string) bool {
	for _, v := range set {
		if v == s {
			return true
		}
	}
	return false
}
