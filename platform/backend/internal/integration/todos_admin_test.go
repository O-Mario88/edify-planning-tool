//go:build integration

package integration

import (
	"context"
	"strconv"
	"strings"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
)

// The Admin's queue (docs/migration/57-todos-cd-admin.md): Go answers the
// Admin; the General Budget's three desks the Admin sits at, the missing
// cost catalogue rates and the partner logins still to set up are built;
// a policy waiting on HR passes the Admin on.
func TestTodosAnswerTheAdminsQueue(t *testing.T) {
	ctx := context.Background()
	const who = "admin@edify.org"
	borrowAccount(t, who)
	token := sessionOf(t, who, seededPassword).GetAccessToken()
	ask := func() (string, error) {
		page, err := pageOf(token, "/todos", nil)
		if err != nil {
			return "", err
		}
		raw, err := protojson.Marshal(page)
		return string(raw), err
	}

	var pending int
	if err := admin.QueryRow(ctx, `SELECT COUNT(*) FROM partner WHERE deleted_at IS NULL AND user_setup_status = 'pending'`).Scan(&pending); err != nil {
		t.Fatal(err)
	}
	got, err := ask()
	if err != nil {
		t.Fatalf("the Admin's queue: %v", err)
	}
	if pending > 0 && !strings.Contains(got, "Configure Partner Users") {
		t.Errorf("%d organisations wait for logins and no row: %s", pending, got)
	}

	cleanup := func(sql string) {
		t.Cleanup(func() { _, _ = admin.Exec(context.Background(), sql) })
	}
	cleanup(`DELETE FROM monthly_work_plan_budget WHERE id LIKE 'gtad-%'`)
	cleanup(`DELETE FROM country_annual_budget WHERE id LIKE 'gtad-%'`)
	for i, status := range []string{"returned_by_rvp", "submitted_to_rvp", "approved_by_rvp"} {
		if _, err := admin.Exec(ctx, `INSERT INTO monthly_work_plan_budget (id, created_at, updated_at, fy, month_key, country_id, generated_at,
  status, program_total, admin_total, total_amount, activity_count, submission_version, country_funding_shortfall, deferred_amount,
  operational_activity_requirement, reference_configuration_missing_count, regional_standard_ceiling, strategic_reserve_requested)
VALUES ($1, now(), now(), '2099', $2, 'Uganda', now(), $3, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0)`,
			"gtad-budget-"+strconv.Itoa(i), "2099-0"+strconv.Itoa(i+1), status); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := admin.Exec(ctx, `INSERT INTO country_annual_budget (id, created_at, updated_at, fy, country_id, target_schools, target_activities,
  planned_staff_visits, planned_partner_visits, core_package_schools, cluster_activities, special_project_total, admin_total, program_total,
  total_amount, monthly_phasing, quarterly_phasing, prior_year_total, status)
VALUES ('gtad-annual-1', now(), now(), '2099', 'Uganda', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, '{}', '{}', 0, 'returned_by_rvp')`); err != nil {
		t.Fatal(err)
	}
	var activity string
	var costMissing bool
	if err := admin.QueryRow(ctx, `SELECT id, cost_missing FROM activity WHERE deleted_at IS NULL AND scheduled_date IS NOT NULL
  AND status NOT IN ('cancelled', 'rejected', 'deferred', 'closed') ORDER BY id LIMIT 1`).Scan(&activity, &costMissing); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `UPDATE activity SET cost_missing = $2 WHERE id = $1`, activity, costMissing)
	})
	if _, err := admin.Exec(ctx, `UPDATE activity SET cost_missing = true WHERE id = $1`, activity); err != nil {
		t.Fatal(err)
	}
	if got, err = ask(); err != nil {
		t.Fatalf("with budgets at every desk: %v", err)
	}
	for _, want := range []string{"Fix Returned General Budget", "Review General Budget", "Prepare Monthly Disbursement Queue",
		"Fix Returned FY2099 Work Plan", "Set Missing Cost Catalogue Rates"} {
		if !strings.Contains(got, want) {
			t.Errorf("no %q row: %s", want, got)
		}
	}

	var doc, docStatus string
	if err := admin.QueryRow(ctx, `SELECT id, status FROM document_asset WHERE archived_at IS NULL ORDER BY id LIMIT 1`).Scan(&doc, &docStatus); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `UPDATE document_asset SET status = $2 WHERE id = $1`, doc, docStatus)
	})
	if _, err := admin.Exec(ctx, `UPDATE document_asset SET status = 'approved' WHERE id = $1`, doc); err != nil {
		t.Fatal(err)
	}
	if _, err := ask(); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("with a policy waiting on HR: %v, want it passed to the existing application", err)
	}
}
