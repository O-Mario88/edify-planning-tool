//go:build integration

package integration

import (
	"context"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
)

// The follow-up sweep is Go's: a Partner scheduling gap the Lead's team does
// not have closes itself (resolved by the system, its history line, the
// Director told, the audit row); a gap Django closes only by hand keeps its
// live figure and stays open.
func TestFollowUpSweepClosesAClearedGap(t *testing.T) {
	ctx := context.Background()
	clear := func() {
		for _, sql := range []string{
			`DELETE FROM notification WHERE context_type = 'PlanningOversightFollowUp' AND context_id LIKE 'gosweep%'`,
			`DELETE FROM planning_oversight_follow_up WHERE id LIKE 'gosweep%'`,
		} {
			if _, err := admin.Exec(ctx, sql); err != nil {
				t.Errorf("clearing: %v", err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	file := func(id, issue, rule string) {
		t.Helper()
		if _, err := admin.Exec(ctx, `INSERT INTO planning_oversight_follow_up (created_at, updated_at, id, fy, period_type, period_start,
  period_end, period_label, country, region_name, program_lead_staff_id, program_lead_user_id, program_lead_name, cceo_name, school_name,
  condition_key, issue_type, metric_key, required_value, planned_value, remaining_value, affected_school_ids, affected_count, snapshot,
  resolution_rule, priority, instruction, instruction_history, assigned_by_id, assigned_by_role, assigned_by_name, assigned_at, due_date,
  status, linked_team_action_ids, linked_note, resolved_by_system, resolution_note, closed_by_id, returned_reason, reminder_count, history,
  activity_label, blocker_owner, module, partner_name, stage)
SELECT now(), now(), $1::varchar, '2026', 'fy', '2025-10-01', '2026-10-01', 'FY 2025/26', 'Uganda', '', sp.id, u.id, u.name, '', '',
  'gosweep|' || $1::varchar, $2::varchar, $2::varchar, 1, 0, 1, '[]', 0, '{}', $3::varchar, 'normal', 'Settle it.', '[]', d.id, 'CountryDirector', d.name, now(), current_date + 7,
  'sent_to_pl', '[]', '', false, '', '', '', 0, '[]', '', '', 'planning', '', 'planning'
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id, "user" d WHERE u.email = 'pl1@edify.org' AND d.email = 'cd@edify.org'`,
			id, issue, rule); err != nil {
			t.Fatalf("filing %s: %v", id, err)
		}
	}
	file("gosweep1", "partner_scheduling_gap", "metric_zero")
	file("gosweep2", "other", "manual")
	checked, resolved, err := planningmonitor.SweepFollowUps(ctx, gateway, nil, time.Now(), nil)
	if err != nil || checked < 2 || resolved < 1 {
		t.Fatalf("the sweep: checked %d resolved %d, %v", checked, resolved, err)
	}
	var status, history string
	var bySystem bool
	if err := admin.QueryRow(ctx, `SELECT status, resolved_by_system, history::text FROM planning_oversight_follow_up WHERE id = 'gosweep1'`).
		Scan(&status, &bySystem, &history); err != nil || status != "resolved_automatically" || !bySystem {
		t.Fatalf("the cleared gap: %s %v %s %v", status, bySystem, history, err)
	}
	var told, audited int
	if err := admin.QueryRow(ctx, `SELECT
  (SELECT count(*) FROM notification n JOIN "user" d ON d.id = n.recipient_id WHERE d.email = 'cd@edify.org'
     AND n.context_id = 'gosweep1' AND n.source_event_type = 'planning_followup_resolved'),
  (SELECT count(*) FROM audit_log WHERE action = 'planning_followup.auto_resolved' AND subject_id = 'gosweep1')`).Scan(&told, &audited); err != nil ||
		told != 1 || audited != 1 {
		t.Fatalf("the Director told %d, audited %d: %v", told, audited, err)
	}
	var open string
	var live *int
	if err := admin.QueryRow(ctx, `SELECT status, live_remaining FROM planning_oversight_follow_up WHERE id = 'gosweep2'`).Scan(&open, &live); err != nil ||
		open != "sent_to_pl" || live == nil {
		t.Fatalf("the manual gap: %s %v %v", open, live, err)
	}
}
