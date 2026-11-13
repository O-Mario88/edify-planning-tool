//go:build integration

package integration

import (
	"context"
	"errors"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
)

// The eighth save, a cluster meeting (docs/migration/49): with no new
// grant, the writer role inserts the meeting with its kind, its cluster and
// head count and one invitation per school, reads the standard meeting item
// the view resolves, and can change neither the meeting's kind nor its
// cluster afterwards. Rolled back, so the test database keeps no row.
func TestTheWriterRoleMakesTheClusterMeetingsWritesAndNoMore(t *testing.T) {
	ctx := context.Background()
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	steps := []struct{ name, statement string }{
		{"resolve the meeting's item", `SELECT id, standard_support, participant_mode FROM activity_catalogue_item
  WHERE workflow_kind = 'cluster_meeting' AND status = 'active' ORDER BY stable_code`},
		{"insert the meeting", `INSERT INTO activity (id, created_at, updated_at, activity_type, fy, quarter, delivery_type,
  executor_type, status, evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents,
  cost_missing, environment, source, responsible_staff_id, purpose_type, secondary_focus_interventions,
  attended_school_ids, ssa_collection_expected, catalogue_item_id, recommendation_reason, recommendation_source,
  override_reason, ssa_alignment, ssa_deviation_reason, planning_source, activity_context_type, support_rationale,
  venue, primary_driver_type, primary_driver_id, driver_reason, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, partner_date_set_by, meeting_kind, cluster_id, expected_participants,
  participants_per_school, cluster_school_count_snapshot, schools_invited, teachers_per_school, leaders_per_school,
  other_per_school, printing_pages, photocopy_pages, photocopy_copies)
VALUES ('role-test-meeting', now(), now(), 'cluster_meeting', '2099', 'Q2', 'staff', 'staff', 'scheduled', 'none',
  'pending', 'none', 0, 0, false, 'development', 'go', 'role-test', 'operational_admin', '{}', '{}', false,
  'role-test-item', '', '{}', '', '', '', 'cluster_planning', 'cluster', '', '', '', '', '', '', '', '', '', '',
  'cluster_leaders', 'role-test-cluster', 4, 2, 6, 2, 0, 2, 0, NULL, NULL, NULL)`},
		{"invite a school", `INSERT INTO cluster_activity_attendance (created_at, updated_at, invited, attended, is_guest,
  teachers, leaders, other, recorded_by, activity_id, school_id)
VALUES (now(), now(), true, false, false, 0, 2, 0, 'role-test', 'role-test-meeting', 'role-test-school')`},
	}
	for _, step := range steps {
		if _, err := tx.Exec(ctx, step.statement); err != nil {
			t.Fatalf("%s: %v", step.name, err)
		}
	}
	_ = tx.Rollback(ctx)

	refused, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = refused.Rollback(ctx) }()
	for _, statement := range []string{
		`UPDATE activity SET meeting_kind = 'training' WHERE false`,
		`UPDATE activity SET cluster_id = NULL WHERE false`,
		`UPDATE activity SET activity_type = 'cluster_training' WHERE false`,
	} {
		if _, err := refused.Exec(ctx, `SAVEPOINT s`); err != nil {
			t.Fatal(err)
		}
		_, err = refused.Exec(ctx, statement)
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "42501" {
			t.Fatalf("%s: want permission denied, got %v", statement, err)
		}
		if _, err := refused.Exec(ctx, `ROLLBACK TO SAVEPOINT s`); err != nil {
			t.Fatal(err)
		}
	}
}

// The Go cluster meeting is off unless EDIFY_GO_SAVES names it (the Group
// Training's switch does not move it), and the switch cannot be loaded in
// production or in the test environment.
func TestTheGoClusterMeetingIsOffByDefaultAndRefusedInProduction(t *testing.T) {
	environment := map[string]string{
		"EDIFY_ENV": "development", "EDIFY_DATABASE_URL": "postgresql://localhost/edify_gorn_test",
		"EDIFY_JWT_SECRET": signingSecret, "EDIFY_EXISTING_APP_URL": "http://127.0.0.1:1",
		"EDIFY_INTERNAL_KEY": "integration-internal-key-0123456789abcdef",
	}
	getenv := func(key string) string { return environment[key] }
	cfg, err := config.Load(getenv)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.GoSaves.ScheduleClusterMeeting {
		t.Fatal("the Go cluster meeting must be off unless EDIFY_GO_SAVES names it")
	}
	environment["EDIFY_GO_SAVES"] = config.SaveScheduleGroupTraining
	if cfg, err := config.Load(getenv); err != nil || cfg.GoSaves.ScheduleClusterMeeting {
		t.Fatalf("the Group Training's switch moved the meeting: %v %v", cfg.GoSaves, err)
	}
	environment["EDIFY_GO_SAVES"] = config.SaveScheduleClusterMeeting
	if cfg, err := config.Load(getenv); err != nil || !cfg.GoSaves.ScheduleClusterMeeting {
		t.Fatalf("development, named: %v %v", cfg.GoSaves, err)
	}
	for _, env := range []string{"production", "test"} {
		environment["EDIFY_ENV"] = env
		cfg, err := config.Load(getenv)
		if err == nil || cfg.GoSaves.ScheduleClusterMeeting {
			t.Fatalf("%s: the switch loaded (%v)", env, cfg.GoSaves)
		}
		if env == "production" && !errors.Is(err, config.ErrProductionNotApproved) {
			t.Fatalf("production: %v", err)
		}
	}
}
