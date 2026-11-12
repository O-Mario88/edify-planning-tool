//go:build integration

package integration

import (
	"context"
	"testing"

	"github.com/jackc/pgx/v5"
)

// The writer role for the first Go save, scheduling a school visit
// (deploy/db/activities_roles.sql; docs/migration/27): the gateway can make
// every write one visit save makes (27.1) — and, by
// TestGatewayRoleCanNeitherWriteNorReadSecrets, nothing after it. Each write
// runs in one read-write transaction that is rolled back, so the test
// database keeps no row. The activity's foreign keys are deferred to commit,
// as Django declares them, so the made-up ids are never checked.
func TestTheActivitiesWriterRoleMakesTheVisitSavesWrites(t *testing.T) {
	ctx := context.Background()
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	steps := []struct{ name, statement string }{
		{"lock the owner's day", `SELECT id FROM daily_visit_batch WHERE responsible_user = 'role-test' FOR UPDATE`},
		{"make the day", `
INSERT INTO daily_visit_batch (id, created_at, updated_at, responsible_user, visit_date, district_type,
  rate_snapshot, daily_pool_amount, school_count, per_school_amount, workload_snapshot)
VALUES ('role-test-day', now(), now(), 'role-test', DATE '2099-01-05', 'primary', '{}', 0, 0, 0, '{}')`},
		{"insert the activity", `
INSERT INTO activity (id, created_at, updated_at, activity_type, fy, quarter, delivery_type, executor_type,
  status, evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents,
  cost_missing, environment, source, school_id, responsible_staff_id, scheduled_date, planned_date,
  planned_month, planned_week, purpose_type, secondary_focus_interventions, attended_school_ids,
  ssa_collection_expected, catalogue_item_id, recommendation_reason, recommendation_source, override_reason,
  ssa_alignment, ssa_deviation_reason, planning_source, activity_context_type, support_rationale, venue,
  primary_driver_type, primary_driver_id, driver_reason, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, partner_date_set_by, meeting_kind, daily_visit_batch_id)
VALUES ('role-test-activity', now(), now(), 'donor_visit', '2099', 'Q2', 'staff', 'staff', 'scheduled',
  'pending', 'pending', 'unpaid', 0, 0, false, 'development', 'go', 'role-test-school', 'role-test',
  now(), DATE '2099-01-05', 1, 1, 'donor_visit', '{}', '{}', false, 'role-test-item', '', '{}', '',
  '', '', 'school_planning', 'school', '', '', '', '', '', '', '', '', '', '', '', 'role-test-day')`},
		{"read the chain's tail", `SELECT seq, hash FROM audit_log WHERE seq IS NOT NULL ORDER BY seq DESC LIMIT 1`},
		{"append to the chain", `
INSERT INTO audit_log (id, seq, action, subject_kind, subject_id, actor_id, actor_role, payload,
  ip_address, user_agent, correlation_id, success, reason, prev_hash, hash, created_at)
VALUES ('role-test-audit', NULL, 'activity.scheduled', 'Activity', 'role-test-activity', 'role-test', 'cceo',
  '{}', NULL, NULL, NULL, true, NULL, NULL, NULL, now())`},
		{"record the event", `
INSERT INTO domain_event_log (id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at)
VALUES ('role-test-event', 'activity.scheduled', 'Activity', 'role-test-activity', 'role-test', '{}', now(), now())`},
		{"mark the ledger", `
INSERT INTO target_ledger_dirty (owner_id, fy, marked_at) VALUES ('role-test', '2099', now())
ON CONFLICT (owner_id, fy) DO UPDATE SET marked_at = EXCLUDED.marked_at`},
		{"keep the costs to follow", `
INSERT INTO daily_visit_costs_to_follow (created_at, updated_at, owners, asked_by, asked_by_role, steps,
  provenance, attempts, held_reason)
VALUES (now(), now(), '["role-test"]', 'role-test', 'cceo', '{"days": [["role-test-day", "role-test"]]}', '{}', 0, '')`},
		{"plan the recommendation", `
UPDATE ssa_recommendation SET state = 'planned', planned_activity_id = 'role-test-activity',
  decided_at = now(), updated_at = now() WHERE false`},
	}
	for _, step := range steps {
		if _, err := tx.Exec(ctx, step.statement); err != nil {
			t.Fatalf("%s: %v", step.name, err)
		}
	}
}
