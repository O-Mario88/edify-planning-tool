package adminops

// The admin_maintenance_generation job (apps.admin_ops.services.
// MaintenanceService.generate_due): every active maintenance template that
// has fallen due becomes one scheduled Admin work item, created as
// AdminWorkItemService.create creates one with no person behind it (the next
// OPS reference, the template's due day, "Begin Maintenance", the creation
// audited), and the template's next due day moves on by its frequency. Inside
// the caller's transaction.

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// referenceAttempts is _next_reference's fifty tries.
const referenceAttempts = 50

// GenerateDueMaintenance is the job for today in Kampala; it says how many
// items it made.
func GenerateDueMaintenance(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location) (int, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	rows, err := tx.Query(ctx, `SELECT id, name, category, COALESCE(description, ''), frequency_days, next_due_date
FROM admin_maintenance_template WHERE active AND next_due_date <= $1 ORDER BY next_due_date`, today.Format(time.DateOnly))
	if err != nil {
		return 0, fmt.Errorf("adminops: reading the due maintenance: %w", err)
	}
	type template struct {
		id, name, category, description string
		every                           int
		due                             time.Time
	}
	var due []template
	for rows.Next() {
		var t template
		if err := rows.Scan(&t.id, &t.name, &t.category, &t.description, &t.every, &t.due); err != nil {
			rows.Close()
			return 0, err
		}
		due = append(due, t)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	for _, t := range due {
		reference, err := nextReference(ctx, tx)
		if err != nil {
			return 0, err
		}
		id := cuid.New()
		day := t.due.Format(time.DateOnly)
		if _, err := tx.Exec(ctx, `INSERT INTO admin_ops_work_item (id, created_at, updated_at, reference, title, category, description,
  severity, status, owner_id, due_date, scheduled_date, next_action, resolution_criteria, verification_note, affected_module,
  affected_route)
VALUES ($1, $2, $2, $3, $4, $5, $6, 'medium', 'scheduled', NULL, $7, $7, 'Begin Maintenance', '', '', '', '')`,
			id, now, reference, firstRunes(t.name, 255), t.category, t.description, day); err != nil {
			return 0, fmt.Errorf("adminops: making the maintenance item: %w", err)
		}
		if _, err := audit.Append(ctx, tx, audit.Entry{
			Action: "admin_ops.work_item.created", SubjectKind: audit.Text("admin_work_item"), SubjectID: audit.Text(id),
			ActorRole: audit.Text("system"), Success: true,
			Payload: map[string]any{"reference": reference, "category": t.category, "scheduled": true},
		}, now); err != nil {
			return 0, fmt.Errorf("adminops: auditing the maintenance item: %w", err)
		}
		if _, err := tx.Exec(ctx, `UPDATE admin_maintenance_template SET next_due_date = next_due_date + $2::int, updated_at = $3
WHERE id = $1`, t.id, t.every, now); err != nil {
			return 0, fmt.Errorf("adminops: moving the template on: %w", err)
		}
	}
	return len(due), nil
}

// nextReference is _next_reference("OPS", ...): the count of items plus one,
// or the first free number after it.
func nextReference(ctx context.Context, tx pgx.Tx) (string, error) {
	var n int
	if err := tx.QueryRow(ctx, `SELECT count(*)::int FROM admin_ops_work_item`).Scan(&n); err != nil {
		return "", fmt.Errorf("adminops: counting the work items: %w", err)
	}
	for attempt := 0; attempt < referenceAttempts; attempt++ {
		candidate := fmt.Sprintf("OPS-%06d", n+1+attempt)
		var taken bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM admin_ops_work_item WHERE reference = $1)`, candidate).
			Scan(&taken); err != nil {
			return "", fmt.Errorf("adminops: reading a reference: %w", err)
		}
		if !taken {
			return candidate, nil
		}
	}
	return "", errors.New("adminops: Could not allocate a reference.")
}

func firstRunes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		r = r[:n]
	}
	return string(r)
}
