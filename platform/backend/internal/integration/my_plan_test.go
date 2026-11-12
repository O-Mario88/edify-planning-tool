//go:build integration

package integration

import (
	"context"
	"strconv"
	"testing"
	"time"

	"connectrpc.com/connect"
)

// The gateway under test has no existing application behind it, so a page
// answered at all here is Go's, and a page Go leaves to the existing
// application fails.

func TestMyPlanOpensEmptyForStaffWhoHoldNothing(t *testing.T) {
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/my-plan", map[string]string{"period": "week", "fy": "2026"})
	if err != nil {
		t.Skipf("the seeded Impact Assessment account holds work here: %v", err)
	}
	if page.GetHeader().GetTitle() != "My Plan" || page.GetHeader().GetActions()[0].GetHref() != "/my-plan/export-drawer?fy=2026&period=week" {
		t.Fatalf("header %+v", page.GetHeader())
	}
	tables := 0
	for _, block := range page.GetBlocks() {
		if table := block.GetTable(); table != nil {
			tables++
			if table.GetCount() != "0" || table.GetEmptyAction().GetHref() != "/planning" {
				t.Errorf("table %+v", table)
			}
		}
	}
	if tables != 4 || page.GetBlocks()[0].GetLinkTabs().GetTabs()[0].GetActive() != true {
		t.Fatalf("%d tables, tabs %+v", tables, page.GetBlocks()[0].GetLinkTabs())
	}
	if page.GetSelection().GetNoun() != "activities selected" {
		t.Fatalf("selection %+v", page.GetSelection())
	}
}

func TestMyPlanIsRefusedToRolesWithoutIt(t *testing.T) {
	borrowAccount(t, "business-transformation@edify.org")
	token := sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("got %v", err)
	}
	// A ?format= the feed has no renderer for is not found for anyone.
	borrowAccount(t, "ia@edify.org")
	token = sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", map[string]string{"format": "csv"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("format: got %v", err)
	}
}

// A training ceiling set for the reader puts My Training Summary on their
// page, which is not Go's yet: the page is left to the existing application.
func TestMyPlanLeavesAPageWithATrainingCeilingToTheExistingApplication(t *testing.T) {
	ctx := context.Background()
	var staffID, trainingID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'ia@edify.org'`).Scan(&staffID); err != nil {
		t.Skipf("no staff profile: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT id FROM activity_catalogue_item ORDER BY id LIMIT 1`).Scan(&trainingID); err != nil {
		t.Skipf("no catalogue item: %v", err)
	}
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", nil); err != nil {
		t.Skipf("the seeded Impact Assessment account holds work here: %v", err)
	}
	const id = "goparitymyplanceiling"
	if _, err := admin.Exec(ctx, `INSERT INTO training_ceiling (created_at, updated_at, id, fy, ceiling, set_by, set_by_role, note, staff_id, training_id)
VALUES (now(), now(), $1, '2027', 5, 'goparity', 'Admin', '', $2, $3)`, id, staffID, trainingID); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM training_ceiling WHERE id = $1`, id); err != nil {
			t.Errorf("removing the ceiling: %v", err)
		}
	})
	if _, err := pageOf(token, "/my-plan", nil); err == nil || connect.CodeOf(err) == connect.CodeNotFound {
		t.Fatalf("the page was answered by Go (or refused): %v", err)
	}
}

// myPlanActivity files one activity of the reader's for the test and removes
// it when the test ends.
func myPlanActivity(t *testing.T, id, staffID, status, planned string) {
	t.Helper()
	ctx := context.Background()
	now := time.Now().In(time.FixedZone("EAT", 3*3600))
	fy := now.Year()
	if now.Month() >= time.October {
		fy++
	}
	quarter := map[bool]string{true: "Q1"}[now.Month() >= time.October]
	if quarter == "" {
		quarter = [...]string{"Q2", "Q2", "Q2", "Q3", "Q3", "Q3", "Q4", "Q4", "Q4"}[now.Month()-1]
	}
	var day any
	if planned != "" {
		day = planned
	}
	if _, err := admin.Exec(ctx, `INSERT INTO activity (created_at, updated_at, id, activity_type, fy, quarter, delivery_type,
  status, evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents, cost_missing,
  environment, source, secondary_focus_interventions, attended_school_ids, ssa_collection_expected, override_reason,
  recommendation_reason, recommendation_source, activity_context_type, planning_source, support_rationale, venue,
  executor_type, driver_reason, primary_driver_id, primary_driver_type, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, ssa_alignment, ssa_deviation_reason, partner_date_set_by, meeting_kind,
  responsible_staff_id, planned_date, activity_purpose_text)
VALUES (now(), now(), $1, 'school_visit', $2, $3, 'staff', $4, 'none', 'none', 'none', 0, 0, false, 'development',
  'goparity', '{}', '{}', false, '', '', '{}', '', '', '', '', 'staff', '', '', '', '', '', '', '', '', '', '', '',
  $5, $6::date, '[Go parity check] My Plan counts')`, id, strconv.Itoa(fy), quarter, status, staffID, day); err != nil {
		t.Fatalf("filing %s: %v", id, err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM activity WHERE id = $1`, id); err != nil {
			t.Errorf("removing %s: %v", id, err)
		}
	})
}

// Closed work is counted on the plan and listed nowhere; work with no date
// is listed (it is still ahead), so its page is the existing application's.
func TestMyPlanCountsClosedWorkAndLeavesListedWorkToTheExistingApplication(t *testing.T) {
	ctx := context.Background()
	var staffID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'ia@edify.org'`).Scan(&staffID); err != nil {
		t.Skipf("no staff profile: %v", err)
	}
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", nil); err != nil {
		t.Skipf("the seeded Impact Assessment account holds work here: %v", err)
	}
	myPlanActivity(t, "goparitymyplanclosed", staffID, "closed",
		time.Now().In(time.FixedZone("EAT", 3*3600)).AddDate(0, 0, -1).Format(time.DateOnly))
	page, err := pageOf(token, "/my-plan", nil)
	if err != nil {
		t.Fatalf("a page with closed work only: %v", err)
	}
	strip := page.GetBlocks()[2].GetStrip().GetMetrics()
	if strip[3].GetValue() != "1" || strip[7].GetValue() != "100%" || strip[4].GetHelper() != "0 Core, 0 Client" {
		t.Fatalf("strip %v", strip)
	}
	last := page.GetBlocks()[len(page.GetBlocks())-1].GetStrip().GetMetrics()
	if last[3].GetValue() != "1 activities" {
		t.Fatalf("breakdown %v", last)
	}
	myPlanActivity(t, "goparitymyplanundated", staffID, "scheduled", "")
	if _, err := pageOf(token, "/my-plan", nil); err == nil || connect.CodeOf(err) == connect.CodeNotFound {
		t.Fatalf("a page listing work was answered by Go (or refused): %v", err)
	}
}

// A Programme Lead who holds no school and has planned nothing opens My Plan
// from Go, with their own Planned and remaining against 280 visits; a
// project ceiling set for them leaves the page to the existing application.
func TestMyPlanDrawsAnEmptyPlannersPlannedAndRemaining(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "pl4@edify.org")
	token := sessionOf(t, "pl4@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/my-plan", map[string]string{"fy": "2026", "list": "staff_queue"})
	if err != nil {
		t.Skipf("the seeded Programme Lead holds work here: %v", err)
	}
	var readiness, list bool
	for _, block := range page.GetBlocks() {
		table := block.GetTable()
		switch {
		case table.GetTitle() == "Planned and remaining · FY 2026":
			readiness = table.GetRows()[0].GetCells()[2].GetText() == "280" &&
				table.GetRows()[0].GetCells()[2].GetHref() == "?fy=2026&list=staff_queue#plan-list"
		case table.GetSubtitle() == "0 schools · Close list":
			list = true
		}
		if strip := block.GetStrip(); strip != nil && strip.GetTitle() == "Plan progress" && strip.GetMetrics()[4].GetHelper() != "of 280 a year" {
			t.Errorf("visits tile %+v", strip.GetMetrics()[4])
		}
	}
	if !readiness || !list {
		t.Fatalf("readiness %v, list %v", readiness, list)
	}
	var staffID, projectID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'pl4@edify.org'`).Scan(&staffID); err != nil {
		t.Skipf("no staff profile: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT id FROM project WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&projectID); err != nil {
		t.Skipf("no project: %v", err)
	}
	var capacityID string
	if err := admin.QueryRow(ctx, `INSERT INTO project_staff_capacity (created_at, updated_at, id, project_id, staff_id, max_schools, set_by, set_by_role)
VALUES (now(), now(), 'goparitymyplancap', $1, $2, 5, 'goparity', 'Admin') RETURNING id`, projectID, staffID).Scan(&capacityID); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.Exec(ctx, `DELETE FROM project_staff_capacity WHERE id = $1`, capacityID) })
	if _, err := pageOf(token, "/my-plan", nil); err == nil {
		t.Fatal("a planner with a project ceiling was drawn by Go")
	}
}

// An officer whose year holds only delivered work opens My Plan from Go:
// the rows of School Visits, Cluster Meetings and Core School Visits, each
// with its Actions menu, and their own Planned and remaining counting the
// visits they planned.
func TestMyPlanDrawsAnOfficersDeliveredWork(t *testing.T) {
	borrowAccount(t, "cceo2@edify.org")
	token := sessionOf(t, "cceo2@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/my-plan", map[string]string{"fy": "2026"})
	if err != nil {
		t.Skipf("the seeded officer's year is not Go's here: %v", err)
	}
	rows := 0
	for _, block := range page.GetBlocks() {
		table := block.GetTable()
		if table.GetTitle() == "Planned and remaining · FY 2026" && table.GetRows()[0].GetCells()[1].GetHref() != "?fy=2026&list=staff_scheduled#plan-list" {
			t.Errorf("planned visits %+v", table.GetRows()[0])
		}
		for _, row := range table.GetRows() {
			last := row.GetCells()[len(row.GetCells())-1]
			if len(last.GetActions()) > 0 {
				rows++
				if last.GetActions()[0].GetLabel() != "View Details" || row.GetTone() != "done" {
					t.Errorf("row %+v", row)
				}
			}
		}
	}
	if rows == 0 {
		t.Fatal("no row of delivered work")
	}
}
