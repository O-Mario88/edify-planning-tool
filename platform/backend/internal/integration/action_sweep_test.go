//go:build integration

package integration

import (
	"context"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/actionsweep"
)

// The delegated-action sweep is Go's: an action about a record that is gone
// closes itself (the audit row, the sender told); an ask only a person
// closes stays open and, past its due date, is flagged overdue with the
// recipient and the sender told.
func TestActionSweepClosesClearedAndFlagsLateActions(t *testing.T) {
	ctx := context.Background()
	clear := func() {
		for _, sql := range []string{
			`DELETE FROM notification WHERE context_type = 'TeamAction' AND context_id LIKE 'goact%'`,
			`DELETE FROM team_action WHERE id LIKE 'goact%'`,
		} {
			if _, err := admin.Exec(ctx, sql); err != nil {
				t.Errorf("clearing: %v", err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	file := func(id, issue, key string, due int) {
		t.Helper()
		if _, err := admin.Exec(ctx, `INSERT INTO team_action (created_at, updated_at, id, condition_key, issue_type, severity, school_id, fy,
  sender_id, sender_role, recipient_id, recipient_role, requested_action, workflow_route, message, priority, due_date, state, detected_at,
  blocked_reason, resolved_by_system, manual_resolution_reason, returned_reason, reminder_count)
SELECT now(), now(), $1::varchar, $3::varchar, $2::varchar, 'high', (SELECT id FROM school ORDER BY id LIMIT 1), '2026', pl.id, 'ProgramLead',
  c.id, 'CCEO', 'Complete or reschedule the overdue activity', '/my-plan', '', 'high', current_date + $4::int, 'open', now(), '', false, '', '', 0
FROM "user" pl, "user" c WHERE pl.email = 'pl1@edify.org' AND c.email = 'cceo@edify.org'`, id, issue, key, due); err != nil {
			t.Fatalf("filing %s: %v", id, err)
		}
	}
	file("goact1", "activity_overdue", "oversight|activity_overdue|activity|nowhere", 5)
	file("goact2", "team_partner_backlog", "team|goact2", -2)
	now := time.Now()
	day := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	if _, err := actionsweep.Sweep(ctx, gateway, nil, now, day, nil); err != nil {
		t.Fatalf("the sweep: %v", err)
	}
	var first, second string
	var bySystem bool
	if err := admin.QueryRow(ctx, `SELECT (SELECT state FROM team_action WHERE id = 'goact1'), (SELECT resolved_by_system FROM team_action WHERE id = 'goact1'),
  (SELECT state FROM team_action WHERE id = 'goact2')`).Scan(&first, &bySystem, &second); err != nil || first != "resolved" || !bySystem || second != "overdue" {
		t.Fatalf("states %q (by the system %v) and %q: %v", first, bySystem, second, err)
	}
	var resolvedNotice, overdueNotices, audited int
	if err := admin.QueryRow(ctx, `SELECT
  (SELECT count(*) FROM notification WHERE context_id = 'goact1' AND source_event_type = 'school_action_resolved'),
  (SELECT count(*) FROM notification WHERE context_id = 'goact2' AND source_event_type IN ('school_action_overdue', 'school_action_overdue_sender')),
  (SELECT count(*) FROM audit_log WHERE action = 'school_action.auto_resolved' AND subject_id = 'goact1')`).
		Scan(&resolvedNotice, &overdueNotices, &audited); err != nil || resolvedNotice != 1 || overdueNotices != 2 || audited != 1 {
		t.Fatalf("notices %d and %d, audited %d: %v", resolvedNotice, overdueNotices, audited, err)
	}
}
