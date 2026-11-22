package accounts

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
)

// CostSettler settles enqueued daily_visit_costs_to_follow rows natively in Go.
type CostSettler interface {
	Settle(ctx context.Context, rows []int64, activityID string) error
}

// DirectRelay replaces HTTPRelay when Django is absent: it executes the real
// business side effects of account_event_relay.py natively in Go:
//   - roles_changed: re-prices open planned days (accommodation rate changes
//     between CCEO and management roles) via gateway_costing + CostSettler.
//   - account_deleted: releases any partner organization's login binding
//     (partner.user_id = NULL, user_setup_status = 'pending') and logs
//     'admin.partner_login_released' in audit_log.
//   - acting_* / other account events: delivers notifications to the affected
//     user(s) via notificationcenter.Writer.
type DirectRelay struct {
	pool    *pgxpool.Pool
	writer  *notificationcenter.Writer
	settler CostSettler
	now     func() time.Time
}

// NewDirectRelay constructs a Django-independent account Event reporter.
func NewDirectRelay(pool *pgxpool.Pool, writer *notificationcenter.Writer) *DirectRelay {
	if pool == nil || writer == nil {
		return nil
	}
	return &DirectRelay{pool: pool, writer: writer, now: time.Now}
}

// WithCostSettler attaches the native Go day-pool settler so roles_changed
// settles open planned days immediately (in addition to leaving durable
// costs_to_follow rows if a transient failure occurs).
func (r *DirectRelay) WithCostSettler(settler CostSettler) *DirectRelay {
	if r != nil {
		r.settler = settler
	}
	return r
}

// Report executes the event's business side effects natively in Go.
func (r *DirectRelay) Report(ctx context.Context, event Event) error {
	now := r.now().UTC()
	switch event.Kind {
	case "roles_changed":
		if err := r.repriceOpenDays(ctx, event.UserID, now); err != nil {
			return err
		}
	case "account_deleted":
		if err := r.releasePartnerLogin(ctx, event.UserID, now); err != nil {
			return err
		}
		return nil
	case "acting_appointed", "acting_activated", "acting_revoked", "acting_ended", "acting_cancelled":
		return r.notifyActing(ctx, event)
	}

	recipient := event.SubjectID
	if recipient == "" {
		recipient = event.UserID
	}
	if recipient == "" {
		return nil
	}
	_, err := r.writer.Deliver(ctx, notificationcenter.Delivery{
		RecipientID:     recipient,
		SenderID:        event.UserID,
		Title:           "Account update: " + event.Kind,
		Body:            fmt.Sprintf("Your account recorded event %q.", event.Kind),
		Category:        "account",
		ContextType:     "user",
		ContextID:       recipient,
		TargetRoute:     "/profile",
		ActionLabel:     "View profile",
		Priority:        "normal",
		SourceEventType: "account." + event.Kind,
		SourceEventID:   fmt.Sprintf("%s:%d", recipient, now.Unix()),
	})
	return err
}

func (r *DirectRelay) repriceOpenDays(ctx context.Context, userID string, now time.Time) error {
	if userID == "" {
		return nil
	}
	today := now.Format(time.DateOnly)
	rows, err := r.pool.Query(ctx,
		`SELECT batch_id, owner_uid FROM gateway_relay_ops.open_planned_batches_for_user($1, $2::date)`,
		userID, today)
	if err != nil {
		return fmt.Errorf("accounts: finding open batches for role change: %w", err)
	}
	defer rows.Close()
	type batchTarget struct {
		batchID  string
		ownerUID string
	}
	var targets []batchTarget
	for rows.Next() {
		var t batchTarget
		if scanErr := rows.Scan(&t.batchID, &t.ownerUID); scanErr != nil {
			return scanErr
		}
		targets = append(targets, t)
	}
	if err := rows.Err(); err != nil {
		return err
	}
	if len(targets) == 0 {
		return nil
	}

	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("accounts: begin reprice enqueue tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var followIDs []int64
	for _, t := range targets {
		var id int64
		if err := tx.QueryRow(ctx,
			`SELECT gateway_costing.enqueue_day_reprice($1, $2, $3, $4, $5)`,
			t.batchID, t.ownerUID, userID, "Admin", now).Scan(&id); err != nil {
			return fmt.Errorf("accounts: enqueuing day reprice for batch %s: %w", t.batchID, err)
		}
		followIDs = append(followIDs, id)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("accounts: committing day reprice enqueue: %w", err)
	}
	if r.settler != nil && len(followIDs) > 0 {
		return r.settler.Settle(ctx, followIDs, "")
	}
	return nil
}

func (r *DirectRelay) releasePartnerLogin(ctx context.Context, userID string, now time.Time) error {
	if userID == "" {
		return nil
	}
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("accounts: begin partner release tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx,
		`SELECT partner_id, partner_name FROM gateway_relay_ops.release_partner_login($1, $2, $3, $4)`,
		userID, "system", "Admin", now)
	if err != nil {
		return fmt.Errorf("accounts: releasing partner login: %w", err)
	}
	type releasedPartner struct {
		id   string
		name string
	}
	var released []releasedPartner
	for rows.Next() {
		var p releasedPartner
		if scanErr := rows.Scan(&p.id, &p.name); scanErr != nil {
			rows.Close()
			return fmt.Errorf("accounts: scanning released partner: %w", scanErr)
		}
		released = append(released, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return fmt.Errorf("accounts: iterating released partners: %w", err)
	}
	for _, p := range released {
		if _, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "admin.partner_login_released",
			SubjectKind: audit.Text("partner"),
			SubjectID:   audit.Text(p.id),
			ActorID:     audit.Text("system"),
			ActorRole:   audit.Text("Admin"),
			Success:     true,
			Reason:      audit.Text("account_deleted"),
			Payload: map[string]any{
				"partnerName":    p.name,
				"releasedUserId": userID,
			},
		}, now); err != nil {
			return fmt.Errorf("accounts: appending partner release audit row: %w", err)
		}
	}
	return tx.Commit(ctx)
}

func (r *DirectRelay) notifyActing(ctx context.Context, event Event) error {
	if event.SubjectID == "" {
		return nil
	}
	var actingFor, actingUser, actingRole, status string
	_ = r.pool.QueryRow(ctx, `
SELECT COALESCE(principal_user_id, ''), COALESCE(acting_user_id, ''),
       COALESCE(acting_role, ''), COALESCE(status, '')
  FROM acting_assignment
 WHERE id = $1`, event.SubjectID).Scan(&actingFor, &actingUser, &actingRole, &status)

	title := "Acting leadership update"
	body := fmt.Sprintf("Acting appointment (%s) updated: %s.", actingRole, event.Kind)
	switch event.Kind {
	case "acting_appointed":
		title = fmt.Sprintf("Appointed as Acting %s", actingRole)
		body = fmt.Sprintf("You have been appointed to cover the %s role.", actingRole)
	case "acting_activated":
		title = fmt.Sprintf("Acting %s cover is now active", actingRole)
		body = fmt.Sprintf("Your Acting %s authority is active.", actingRole)
	case "acting_revoked", "acting_ended", "acting_cancelled":
		title = fmt.Sprintf("Acting %s cover ended", actingRole)
		body = fmt.Sprintf("Your Acting %s appointment has ended (%s).", actingRole, status)
	}

	recipients := map[string]bool{}
	if actingUser != "" {
		recipients[actingUser] = true
	}
	if actingFor != "" {
		recipients[actingFor] = true
	}
	if len(recipients) == 0 && event.UserID != "" {
		recipients[event.UserID] = true
	}
	for rec := range recipients {
		if _, err := r.writer.Deliver(ctx, notificationcenter.Delivery{
			RecipientID:     rec,
			SenderID:        event.UserID,
			Title:           title,
			Body:            body,
			Category:        "acting",
			ContextType:     "acting_assignment",
			ContextID:       event.SubjectID,
			TargetRoute:     "/acting-appointments",
			ActionLabel:     "View cover",
			Priority:        "high",
			SourceEventType: event.Kind,
			SourceEventID:   event.SubjectID,
		}); err != nil {
			return err
		}
	}
	return nil
}
