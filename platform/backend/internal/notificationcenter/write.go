package notificationcenter

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// Delivery is one workflow notification to insert natively in Go through
// gateway_notifications.deliver (idempotent on recipient + context + event).
type Delivery struct {
	RecipientID     string
	SenderID        string
	Title           string
	Body            string
	Category        string
	ContextType     string
	ContextID       string
	TargetRoute     string
	ActionLabel     string
	ActionRequired  bool
	Priority        string
	SourceEventType string
	SourceEventID   string
}

// Writer writes and marks notifications read natively in PostgreSQL without
// calling Django (M11).
type Writer struct {
	pool *pgxpool.Pool
	now  func() time.Time
}

// NewWriter builds a native notification writer over pool.
func NewWriter(pool *pgxpool.Pool, now func() time.Time) *Writer {
	if now == nil {
		now = time.Now
	}
	return &Writer{pool: pool, now: now}
}

// Deliver writes one notification idempotently. Returns true when a new row
// was inserted, false when deduplicated or the recipient is inactive.
func (w *Writer) Deliver(ctx context.Context, d Delivery) (bool, error) {
	if strings.TrimSpace(d.RecipientID) == "" || strings.TrimSpace(d.Title) == "" {
		return false, fmt.Errorf("notificationcenter: recipient and title are required")
	}
	now := w.now().UTC()
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return false, fmt.Errorf("notificationcenter: starting deliver tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var created bool
	err = tx.QueryRow(ctx, `
SELECT gateway_notifications.deliver($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`,
		cuid.New(), d.RecipientID, d.SenderID, d.Title, d.Body, d.Category,
		d.ContextType, d.ContextID, d.TargetRoute, d.ActionLabel, d.ActionRequired,
		d.Priority, d.SourceEventType, d.SourceEventID, now,
	).Scan(&created)
	if err != nil {
		return false, fmt.Errorf("notificationcenter: delivering notification: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return false, fmt.Errorf("notificationcenter: committing delivery: %w", err)
	}
	return created, nil
}

// MarkRead marks one unread notification as read for its owner.
func (w *Writer) MarkRead(ctx context.Context, notificationID, ownerUserID string) (int, error) {
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, fmt.Errorf("notificationcenter: starting mark_read tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var changed int
	if err := tx.QueryRow(ctx, `SELECT gateway_notifications.mark_read($1, $2, $3)`,
		notificationID, ownerUserID, w.now().UTC()).Scan(&changed); err != nil {
		return 0, fmt.Errorf("notificationcenter: marking notification read: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("notificationcenter: committing mark_read: %w", err)
	}
	return changed, nil
}

// MarkAllRead marks all unread notifications as read for ownerUserID.
func (w *Writer) MarkAllRead(ctx context.Context, ownerUserID string) (int, error) {
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, fmt.Errorf("notificationcenter: starting mark_all_read tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var changed int
	if err := tx.QueryRow(ctx, `SELECT gateway_notifications.mark_all_read($1, $2)`,
		ownerUserID, w.now().UTC()).Scan(&changed); err != nil {
		return 0, fmt.Errorf("notificationcenter: marking all notifications read: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("notificationcenter: committing mark_all_read: %w", err)
	}
	return changed, nil
}

func (w *Writer) archive(ctx context.Context, ownerID, targetID string) (int, error) {
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, err
	}
	defer tx.Rollback(ctx)
	var changed int
	if err := tx.QueryRow(ctx, "SELECT gateway_notifications.archive($1, $2)", ownerID, targetID).Scan(&changed); err != nil {
		return 0, err
	}
	return changed, tx.Commit(ctx)
}

// ResolveContext marks open notifications for a context (and optional event type)
// as resolved (e.g. closing overdue reminders when an activity is completed).
func (w *Writer) ResolveContext(ctx context.Context, eventType, contextType, contextID string) (int, error) {
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, fmt.Errorf("notificationcenter: starting resolve_context tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var changed int
	if err := tx.QueryRow(ctx, `SELECT gateway_notifications.resolve_context($1, $2, $3, $4)`,
		eventType, contextType, contextID, w.now().UTC()).Scan(&changed); err != nil {
		return 0, fmt.Errorf("notificationcenter: resolving context notifications: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("notificationcenter: committing resolve_context: %w", err)
	}
	return changed, nil
}
