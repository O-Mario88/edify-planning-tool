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

// The seventh save, a cluster Group Training (docs/migration/38): the writer
// role reads the cluster, its members' clustering, the catalogue's cluster
// delivery and the cluster's sessions, and inserts the session with its
// cluster, head count and materials and one invitation per school (the id
// from the table's own sequence). It can change none of them afterwards,
// remove no invitation and write no cluster. Rolled back, so the test
// database keeps no row; the foreign keys are deferred, as Django declares
// them.
func TestTheWriterRoleMakesTheGroupTrainingsWritesAndNoMore(t *testing.T) {
	ctx := context.Background()
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	steps := []struct{ name, statement string }{
		{"read the cluster", `SELECT id, responsible_staff_id, district_id FROM cluster WHERE deleted_at IS NULL LIMIT 1`},
		{"read the members' clustering", `SELECT count(*) FROM school WHERE cluster_status = 'clustered'`},
		{"read the cluster catalogue", `SELECT id FROM activity_catalogue_item WHERE cluster_delivery_allowed LIMIT 1`},
		{"read the cluster's sessions", `SELECT focus_intervention FROM activity WHERE cluster_id = 'x' AND fy = '2099'
  ORDER BY planned_date DESC, created_at DESC LIMIT 1`},
		{"insert the session", `INSERT INTO activity (id, created_at, updated_at, activity_type, fy, quarter, delivery_type,
  executor_type, status, evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents,
  cost_missing, environment, source, responsible_staff_id, purpose_type, secondary_focus_interventions,
  attended_school_ids, ssa_collection_expected, catalogue_item_id, recommendation_reason, recommendation_source,
  override_reason, ssa_alignment, ssa_deviation_reason, planning_source, activity_context_type, support_rationale,
  venue, primary_driver_type, primary_driver_id, driver_reason, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, partner_date_set_by, meeting_kind, cluster_id, expected_participants,
  participants_per_school, cluster_school_count_snapshot, schools_invited, teachers_per_school, leaders_per_school,
  other_per_school, printing_pages, photocopy_pages, photocopy_copies)
VALUES ('role-test-session', now(), now(), 'cluster_training', '2099', 'Q2', 'staff', 'staff', 'scheduled', 'none',
  'pending', 'none', 0, 0, false, 'development', 'go', 'role-test', 'focus_intervention', '{}', '{}', false,
  'role-test-item', '', '{}', '', '', '', 'cluster_planning', 'cluster', '', '', '', '', '', '', '', '', '', '', '',
  'role-test-cluster', 6, 3, 4, 2, 2, 1, 0, NULL, 4, 2)`},
		{"invite a school", `INSERT INTO cluster_activity_attendance (created_at, updated_at, invited, attended, is_guest,
  teachers, leaders, other, recorded_by, activity_id, school_id)
VALUES (now(), now(), true, false, false, 2, 1, 0, 'role-test', 'role-test-session', 'role-test-school')`},
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
		`UPDATE activity SET cluster_id = NULL WHERE false`,
		`UPDATE activity SET expected_participants = 0 WHERE false`,
		`UPDATE activity SET schools_invited = 0 WHERE false`,
		`UPDATE cluster_activity_attendance SET attended = true WHERE false`,
		`UPDATE cluster_activity_attendance SET school_id = 'x' WHERE false`,
		`DELETE FROM cluster_activity_attendance WHERE false`,
		`UPDATE cluster SET updated_at = now() WHERE false`,
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

// The cluster's lock (38.5 §2): the gateway takes the row lock Django's
// cluster saves take, so another session's FOR UPDATE waits; it can neither
// lock nor write a cluster itself, nor become the lock's owner, nor add a
// function beside the lock.
func TestTheClusterLockBlocksAnotherSessionsLock(t *testing.T) {
	ctx := context.Background()
	var clusterID string
	if err := admin.QueryRow(ctx, `SELECT id FROM cluster WHERE deleted_at IS NULL LIMIT 1`).Scan(&clusterID); err != nil {
		t.Fatal(err)
	}
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var locked bool
	if err := tx.QueryRow(ctx, `SELECT gateway_lock.lock_cluster($1)`, clusterID).Scan(&locked); err != nil || !locked {
		t.Fatalf("the gateway's lock: %v %v", locked, err)
	}
	var missing bool
	if err := tx.QueryRow(ctx, `SELECT gateway_lock.lock_cluster('no-such-cluster')`).Scan(&missing); err != nil || missing {
		t.Fatalf("an unknown cluster locks nothing: %v %v", missing, err)
	}

	other, err := admin.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = other.Rollback(ctx) }()
	_, err = other.Exec(ctx, `SELECT 1 FROM cluster WHERE id = $1 FOR UPDATE NOWAIT`, clusterID)
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "55P03" {
		t.Fatalf("another session's FOR UPDATE must wait for the gateway's lock, got %v", err)
	}

	for name, statement := range map[string]string{
		"lock a cluster itself": `SELECT 1 FROM cluster WHERE id = '` + clusterID + `' FOR UPDATE`,
		"write a cluster":       `UPDATE cluster SET updated_at = updated_at WHERE id = '` + clusterID + `'`,
		"become the lock role":  `SET ROLE edify_cluster_lock_owner`,
		"add a lock function":   `CREATE FUNCTION gateway_lock.another() RETURNS int LANGUAGE sql AS 'SELECT 1'`,
	} {
		conn, err := gateway.Acquire(ctx)
		if err != nil {
			t.Fatal(err)
		}
		_, err = conn.Conn().PgConn().Exec(ctx, `BEGIN READ WRITE; `+statement).ReadAll()
		if !errors.As(err, &pgErr) || pgErr.Code != "42501" {
			t.Fatalf("%s: must be refused for privilege, got %v", name, err)
		}
		_, _ = conn.Conn().PgConn().Exec(ctx, "ROLLBACK").ReadAll()
		conn.Release()
	}
}

// The Go Group Training is off unless EDIFY_GO_SAVES names it, and the
// switch cannot be loaded in production or in the test environment.
func TestTheGoGroupTrainingIsOffByDefaultAndRefusedInProduction(t *testing.T) {
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
	if cfg.GoSaves.ScheduleGroupTraining {
		t.Fatal("the Go Group Training must be off unless EDIFY_GO_SAVES names it")
	}
	environment["EDIFY_GO_SAVES"] = config.SaveScheduleTrainingPair
	if cfg, err := config.Load(getenv); err != nil || cfg.GoSaves.ScheduleGroupTraining {
		t.Fatalf("another save's switch moved the Group Training: %v %v", cfg.GoSaves, err)
	}
	environment["EDIFY_GO_SAVES"] = config.SaveScheduleGroupTraining
	if cfg, err := config.Load(getenv); err != nil || !cfg.GoSaves.ScheduleGroupTraining {
		t.Fatalf("development, named: %v %v", cfg.GoSaves, err)
	}
	for _, env := range []string{"production", "test"} {
		environment["EDIFY_ENV"] = env
		cfg, err := config.Load(getenv)
		if err == nil || cfg.GoSaves.ScheduleGroupTraining {
			t.Fatalf("%s: the switch loaded (%v)", env, cfg.GoSaves)
		}
		if env == "production" && !errors.Is(err, config.ErrProductionNotApproved) {
			t.Fatalf("production: %v", err)
		}
	}
}
