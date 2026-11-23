//go:build integration

package integration

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
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

// The school row lock (27.8 §2): the gateway takes the same row lock the
// existing save takes, through gateway_lock.lock_school, and a second
// session asking for that row's lock waits for it; the gateway still cannot
// write the school or become the lock's owner.
func TestTheSchoolLockBlocksAnotherSessionsLock(t *testing.T) {
	ctx := context.Background()
	var schoolID string
	if err := admin.QueryRow(ctx, `SELECT id FROM school WHERE deleted_at IS NULL LIMIT 1`).Scan(&schoolID); err != nil {
		t.Fatal(err)
	}
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var locked bool
	if err := tx.QueryRow(ctx, `SELECT gateway_lock.lock_school($1)`, schoolID).Scan(&locked); err != nil || !locked {
		t.Fatalf("the gateway's lock: %v %v", locked, err)
	}

	other, err := admin.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = other.Rollback(ctx) }()
	_, err = other.Exec(ctx, `SELECT 1 FROM school WHERE id = $1 FOR UPDATE NOWAIT`, schoolID)
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "55P03" {
		t.Fatalf("another session's FOR UPDATE must wait for the gateway's lock, got %v", err)
	}

	for name, statement := range map[string]string{
		"write a school":       `UPDATE school SET updated_at = updated_at WHERE id = '` + schoolID + `'`,
		"become the lock role": `SET ROLE edify_school_lock_owner`,
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

// fakePricing answers the day check as the existing application would for
// a day it pools; the refusals below are all met before it is asked, or
// handed on, so nothing is written.
type fakePricing struct{ asked int }

func (f *fakePricing) DayCheck(context.Context, map[string]any) (activities.DayVerdict, error) {
	f.asked++
	return activities.DayVerdict{Pooled: true}, nil
}

func (f *fakePricing) Settle(context.Context, []int64, string) error { return nil }

// The save's refusals and hand-ons, made as the gateway against the test
// database; none of them writes a row (the saves themselves are proved in
// shadow, docs/migration/27 §27.9).
func TestTheVisitSaveRefusesAndHandsOnInTheExistingWords(t *testing.T) {
	ctx := context.Background()
	pricing := &fakePricing{}
	svc, err := activities.NewService(gateway, pricing, slog.New(slog.NewTextHandler(io.Discard, nil)),
		func() time.Time { return time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC) })
	if err != nil {
		t.Fatal(err)
	}
	svc.WithVisitRequests(coreforms.NewService(gateway, func() time.Time { return time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC) }))
	principal := func(email string) auth.Principal {
		account, err := identity.NewStore(gateway).LoadAccount(ctx, borrowAccount(t, email))
		if err != nil {
			t.Fatal(err)
		}
		return auth.Principal{Account: account}
	}
	cceo := principal("cceo@edify.org")
	var client, core string
	if err := admin.QueryRow(ctx, `
WITH own AS (SELECT DISTINCT ON (a.school_id) a.school_id, a.staff_id FROM staff_school_assignment a ORDER BY a.school_id, a.created_at)
SELECT
  (SELECT s.school_id FROM school s JOIN own ON own.school_id = s.id WHERE own.staff_id = $1 AND s.deleted_at IS NULL
     AND s.school_type = 'client' AND s.operational_status = 'active' ORDER BY s.school_id LIMIT 1),
  (SELECT s.school_id FROM school s JOIN own ON own.school_id = s.id WHERE own.staff_id = $1 AND s.deleted_at IS NULL
     AND s.school_type = 'core' ORDER BY s.school_id LIMIT 1)`, cceo.StaffProfileID).Scan(&client, &core); err != nil {
		t.Fatal(err)
	}
	var course string
	if err := admin.QueryRow(ctx, `SELECT id FROM activity_catalogue_item WHERE stable_code = 'EDTECH_FOUNDATIONS'`).Scan(&course); err != nil {
		t.Fatal(err)
	}
	visit := func(school, purpose, day string) activities.Request {
		return activities.Request{SchoolID: school, Purpose: purpose, Date: day}
	}
	var before int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity`).Scan(&before); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name    string
		who     auth.Principal
		req     activities.Request
		refusal string
		handOn  bool
	}{
		{"the Admin plans nothing", principal("admin@edify.org"), visit(client, "donor_visit", "2026-11-20"),
			"Planning belongs to the staff member responsible for the school.", false},
		{"a day that has passed", cceo, visit(client, "donor_visit", "2026-11-10"),
			"10 November 2026 has passed. Schedule work from 12 November 2026 onwards.", false},
		{"no day", cceo, visit(client, "donor_visit", ""), "Pick the date this is planned for before scheduling it.", false},
		{"a Core school's package visit", cceo, visit(core, "training_follow_up", "2026-11-20"), "", true},
		{"a Core school's donor visit is outside the package", cceo, visit(core, "donor_visit", "2026-11-10"),
			"10 November 2026 has passed. Schedule work from 12 November 2026 onwards.", false},
		// The pair is Go's since docs/migration/32: with no course it is
		// refused in the view's words before anything is read.
		{"In-school Training with no course", cceo, visit(client, "in_school_training", "2026-11-20"),
			"Select the Training to deliver.", false},
		{"a pinned item nobody knows", cceo, activities.Request{SchoolID: client, Purpose: "donor_visit",
			Date: "2026-11-20", CatalogueItemID: "no-such-item"}, "", true},
		// visit_owner_for: anybody else's school is the visit of whoever is
		// going, so Go reaches the rules past the portfolio.
		{"another CCEO at this officer's school", principal("cceo1@edify.org"), visit(client, "donor_visit", "2026-11-10"),
			"10 November 2026 has passed. Schedule work from 12 November 2026 onwards.", false},
		{"the Country Director at this officer's school", principal("cd@edify.org"), visit(client, "donor_visit", "2026-11-10"),
			"10 November 2026 has passed. Schedule work from 12 November 2026 onwards.", false},
		{"the Accountant asks without saying why", principal("accountant@edify.org"), visit(client, "donor_visit", "2026-11-20"),
			"Explain why you need to visit this school.", false},
		{"another CCEO's training at this officer's school", principal("cceo1@edify.org"),
			activities.Request{SchoolID: client, Purpose: "in_school_training", Date: "2026-11-10", CatalogueItemID: course, Focus: "leadership"},
			"10 November 2026 has passed. Schedule work from 12 November 2026 onwards.", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := svc.Schedule(ctx, tt.who, tt.req, activities.Origin{IP: "127.0.0.1"})
			var refused *activities.Refusal
			switch {
			case tt.handOn:
				if !errors.Is(err, activities.ErrHandOn) {
					t.Fatalf("must be handed on, got %v", err)
				}
			case !errors.As(err, &refused) || !strings.HasPrefix(refused.Message, tt.refusal):
				t.Fatalf("got %v, want %q", err, tt.refusal)
			}
		})
	}
	var after int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity`).Scan(&after); err != nil || after != before {
		t.Fatalf("a refused or handed-on save wrote %d activities (%v)", after-before, err)
	}
	if pricing.asked != 0 {
		t.Fatalf("the pricing was asked %d times before a refusal it never reaches", pricing.asked)
	}
}
