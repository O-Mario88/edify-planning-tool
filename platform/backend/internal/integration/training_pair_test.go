//go:build integration

package integration

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
)

// The fifth save, an In-school Training and its school visit
// (docs/migration/32): the writer role reads the course, its mapping and
// the officer's ceiling, and inserts the two rows joined (the visit first,
// the training naming it). It cannot join them afterwards: the pair column
// stays one an UPDATE never reaches (dbguard.protectedColumns). Rolled back,
// so the test database keeps no row; the foreign keys are deferred, as
// Django declares them.
func TestTheWriterRoleMakesThePairsWritesAndCannotRejoinThem(t *testing.T) {
	ctx := context.Background()
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	insert := func(id, kind, paired string) string {
		return `INSERT INTO activity (id, created_at, updated_at, activity_type, fy, quarter, delivery_type, executor_type,
  status, evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents, cost_missing,
  environment, source, school_id, responsible_staff_id, purpose_type, secondary_focus_interventions,
  attended_school_ids, ssa_collection_expected, catalogue_item_id, recommendation_reason, recommendation_source,
  override_reason, ssa_alignment, ssa_deviation_reason, planning_source, activity_context_type, support_rationale,
  venue, primary_driver_type, primary_driver_id, driver_reason, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, partner_date_set_by, meeting_kind, training_course_id,
  paired_school_visit_id)
VALUES ('` + id + `', now(), now(), '` + kind + `', '2099', 'Q2', 'staff', 'staff', 'scheduled', 'none', 'pending',
  'none', 0, 0, false, 'development', 'go', 'role-test-school', 'role-test', 'in_school_training', '{}', '{}', false,
  'role-test-item', '', '{}', '', '', '', 'school_planning', 'school', '', '', '', '', '', '', '', '', '', '', '',
  ` + paired + `)`
	}
	steps := []struct{ name, statement string }{
		{"read the course", `SELECT id, stable_code, display_name, workflow_kind, training_category, ssa_indicator_label,
  universal_training, staff_delivery_allowed FROM activity_catalogue_item WHERE is_training_course LIMIT 1`},
		{"read its mapping", `SELECT mapping_mode, intervention, is_primary FROM activity_intervention_mapping LIMIT 1`},
		{"read the ceiling", `SELECT EXISTS (SELECT 1 FROM training_ceiling WHERE staff_id = 'x' AND training_id = 'y' AND fy = '2099')`},
		{"insert the visit", insert("role-test-visit", "school_visit", "NULL, NULL")},
		{"insert the training naming it", insert("role-test-training", "in_school_training", "'role-test-course', 'role-test-visit'")},
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
		`UPDATE activity SET paired_school_visit_id = NULL WHERE false`,
		`UPDATE activity SET training_course_id = NULL WHERE false`,
		`UPDATE training_ceiling SET ceiling = 0 WHERE false`,
	} {
		_, err := refused.Exec(ctx, `SAVEPOINT s`)
		if err != nil {
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

// The app's In-school Training reaches Go only behind
// EDIFY_GO_SAVES=schedule_training_pair: with the switch unset (or only the
// visit's named) the save is forwarded exactly as before, and the switch
// cannot be loaded in production or in the test environment.
func TestTheGoTrainingPairIsOffByDefaultAndRefusedInProduction(t *testing.T) {
	ctx := context.Background()
	var mu sync.Mutex
	var asked []string
	existing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		asked = append(asked, r.Method+" "+r.URL.RequestURI())
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"saved": false, "error": "the existing application's answer"}`)
	}))
	defer existing.Close()
	environment := map[string]string{
		"EDIFY_ENV": "development", "EDIFY_DATABASE_URL": "postgresql://localhost/edify_gorn_test",
		"EDIFY_JWT_SECRET": signingSecret, "EDIFY_EXISTING_APP_URL": existing.URL,
		"EDIFY_INTERNAL_KEY": "integration-internal-key-0123456789abcdef",
	}
	getenv := func(key string) string { return environment[key] }
	cfg, err := config.Load(getenv)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.GoSaves.ScheduleTrainingPair {
		t.Fatal("the Go training pair must be off unless EDIFY_GO_SAVES names it")
	}
	gatewayServer := httptest.NewServer(server.New(cfg, gateway, nil, slog.New(slog.NewTextHandler(io.Discard, nil))))
	defer gatewayServer.Close()
	var userID, schoolID string
	if err := admin.QueryRow(ctx, `SELECT u.id, s.id FROM "user" u
JOIN staff_profile sp ON sp.user_id = u.id
JOIN school s ON s.account_owner_id = sp.id AND s.deleted_at IS NULL
WHERE u.email = 'cceo@edify.org' LIMIT 1`).Scan(&userID, &schoolID); err != nil {
		t.Fatal(err)
	}
	var before int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity WHERE school_id = $1`, schoolID).Scan(&before); err != nil {
		t.Fatal(err)
	}
	drawers := screensv1connect.NewPlanningDrawerServiceClient(http.DefaultClient, gatewayServer.URL)
	answer, err := drawers.SavePlanningDrawer(ctx, authed(&screensv1.SavePlanningDrawerRequest{
		SchoolId: schoolID, Kind: "schedule", Values: map[string]string{
			"purpose_of_visit": "in_school_training", "scheduled_date": time.Now().AddDate(0, 0, 14).Format(time.DateOnly),
			"catalogue_item_id": "a-course", "facilitating_partner_id": "", "executor_type": "staff", "delivery_type": "staff",
		},
	}, token(t, userID, "CCEO", time.Minute)))
	if err != nil {
		t.Fatal(err)
	}
	if answer.Msg.GetError() != "the existing application's answer" {
		t.Fatalf("the save was not the existing application's: %v", answer.Msg)
	}
	mu.Lock()
	calls := strings.Join(asked, "; ")
	mu.Unlock()
	if calls != "POST /api/mobile/v1/schools/"+schoolID+"/planning/schedule" {
		t.Fatalf("the existing application was asked %q", calls)
	}
	var after int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity WHERE school_id = $1`, schoolID).Scan(&after); err != nil {
		t.Fatal(err)
	}
	if after != before {
		t.Fatalf("activities %d → %d: Go wrote with the switch off", before, after)
	}

	environment["EDIFY_GO_SAVES"] = config.SaveScheduleTrainingPair
	for _, env := range []string{"production", "test"} {
		environment["EDIFY_ENV"] = env
		cfg, err := config.Load(getenv)
		if err == nil || cfg.GoSaves.ScheduleTrainingPair {
			t.Fatalf("%s: the switch loaded (%v)", env, cfg.GoSaves)
		}
		if env == "production" && !errors.Is(err, config.ErrProductionNotApproved) {
			t.Fatalf("production: %v", err)
		}
	}
}
