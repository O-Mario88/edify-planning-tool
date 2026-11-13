//go:build integration

package integration

import (
	"context"
	"strconv"
	"testing"
	"time"

	"connectrpc.com/connect"
)

// The gateway under test has no existing application behind it, so a Work
// Plan answered at all here is Go's.

func TestWorkPlanOpensWithItsApprovalTabsFiltersAndTables(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	token := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/work-plan", map[string]string{"view": "quarter", "period": "Q2", "fy": "2026"})
	if err != nil {
		t.Fatal(err)
	}
	if h := page.GetHeader(); h.GetTitle() != "Work Plan" || len(h.GetActions()) != 1 || h.GetActions()[0].GetHref() != "/work-plan/add" {
		t.Fatalf("header %+v", h)
	}
	blocks := page.GetBlocks()
	if blocks[0].GetPanel().GetTitle() != "FY 2026 Work Plan approval" {
		t.Fatalf("approval %+v", blocks[0])
	}
	tabs := blocks[1].GetLinkTabs().GetTabs()
	if len(tabs) != 3 || !tabs[1].GetActive() || tabs[1].GetHref() != "/work-plan?fy=2026&view=quarter&period=Q1" {
		t.Fatalf("tabs %+v", tabs)
	}
	f := blocks[2].GetFilters()
	if f.GetFilters()[1].GetName() != "period" || f.GetFilters()[1].GetValue() != "Q2" || f.GetHidden()["fy_prev"] != "2026" {
		t.Fatalf("filters %+v", f)
	}
	last := blocks[len(blocks)-1].GetTable()
	if len(last.GetColumns()) != 15 || last.GetColumns()[14].GetLabel() != "Action" {
		t.Fatalf("detail %+v", last)
	}
}

func TestWorkPlanIsRefusedToRolesWithoutIt(t *testing.T) {
	borrowAccount(t, "business-transformation@edify.org")
	token := sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/work-plan", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("got %v", err)
	}
}

// An officer's own scheduled visit this month: one row of the Detailed
// Activity Plan with its cost and breakdown, the menu of their own work, a
// tick box, and the summary line and strip counting it.
func TestWorkPlanListsAnOfficersOwnVisitWithItsCost(t *testing.T) {
	ctx := context.Background()
	var staffID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo1@edify.org'`).Scan(&staffID); err != nil {
		t.Skipf("no staff profile: %v", err)
	}
	kampala, _ := time.LoadLocation("Africa/Nairobi")
	today := time.Now().In(kampala)
	day := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC).AddDate(0, 0, 1)
	if day.Month() != today.Month() {
		day = day.AddDate(0, 0, -2)
	}
	fy := day.Year()
	if day.Month() >= time.October {
		fy++
	}
	const id, line = "goparityworkplan1", "goparityworkplanline1"
	if _, err := admin.Exec(ctx, `INSERT INTO activity (created_at, updated_at, id, activity_type, fy, quarter, delivery_type, status,
  evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents, cost_missing, environment, source,
  secondary_focus_interventions, attended_school_ids, ssa_collection_expected, override_reason, recommendation_reason,
  recommendation_source, activity_context_type, planning_source, support_rationale, venue, executor_type, driver_reason,
  primary_driver_id, primary_driver_type, delivery_contact_name, approval_owner_id, owner_decision_note, visit_justification,
  ssa_alignment, ssa_deviation_reason, partner_date_set_by, meeting_kind, responsible_staff_id, planned_date, activity_name_snapshot)
VALUES (now(), now(), $1, 'donor_visit', $2, 'Q1', 'staff', 'scheduled', 'none', '', 'none', 0, 0, false, 'test', 'test',
  '{}', '{}', false, '', '', '{}', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', $3, $4, '[Go parity check] visit')`,
		id, strconv.Itoa(fy), staffID, day); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM activity_schedule_cost_line WHERE id = $1`, line)
		_, _ = admin.Exec(ctx, `DELETE FROM activity WHERE id = $1`, id)
	})
	if _, err := admin.Exec(ctx, `INSERT INTO activity_schedule_cost_line (created_at, updated_at, id, cost_setting_key, label,
  unit_cost, quantity, amount, cost_setting_version, activity_id, currency, vendor_paid)
VALUES (now(), now(), $1, 'goparity_lunch', '[Go parity check] Lunch', 12000, 1, 12000, 1, $2, 'UGX', false)`, line, id); err != nil {
		t.Fatal(err)
	}
	borrowAccount(t, "cceo1@edify.org")
	token := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/work-plan", map[string]string{"fy": strconv.Itoa(fy), "period": strconv.Itoa(int(day.Month()))})
	if err != nil {
		t.Fatal(err)
	}
	blocks := page.GetBlocks()
	detail := blocks[len(blocks)-1].GetTable()
	found := false
	for _, r := range detail.GetRows() {
		if r.GetPickId() != id {
			continue
		}
		found = true
		cells := r.GetCells()
		if cells[1].GetText() != "Visit" || cells[6].GetText() != "Donor Visit" ||
			cells[11].GetText() != "UGX 12,000 Breakdown[Go parity check] Lunch: UGX 12,000" || cells[13].GetText() != "Scheduled" {
			t.Errorf("row %+v", cells)
		}
		actions := cells[14].GetActions()
		if len(actions) != 4 || actions[0].GetLabel() != "Complete" || actions[1].GetLabel() != "Reschedule" ||
			actions[2].GetKey() != "danger" || actions[3].GetHref() != "/my-plan/"+id {
			t.Errorf("actions %+v", actions)
		}
	}
	if !found {
		t.Fatalf("the visit is not listed: %+v", detail.GetRows())
	}
	if page.GetSelection() == nil {
		t.Error("no bar for the ticked rows")
	}
	for _, b := range blocks {
		if s := b.GetStrip(); s != nil && s.GetMetrics()[2].GetLabel() == "Plan-Derived Budget" && s.GetMetrics()[2].GetValue() == "UGX 0" {
			t.Errorf("the strip does not count the visit's cost: %+v", s)
		}
	}
}
