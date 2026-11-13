//go:build integration

package integration

import (
	"context"
	"testing"
)

// The By staff and Schools tabs of the Training Summary, answered by Go (the
// gateway under test has no existing application behind it): a hand-over
// waiting for the Partner's date and a ceiling of one the Lead set on
// themselves read as the ceiling reached, and the school is listed
// as awaiting the Partner, opening Partner Oversight.
func TestTheTrainingSummaryTabsReadAHandoverAndACeiling(t *testing.T) {
	fileHandover(t, "pl1@edify.org")
	page := trainingSummaryOf(t, "pl1@edify.org", map[string]string{"view": "trainings", "tab": "schools"})
	fy := page.GetBlocks()[1].GetFilters().GetFilters()[0].GetValue()
	ctx := context.Background()
	if _, err := admin.Exec(ctx, `INSERT INTO training_ceiling (id, created_at, updated_at, fy, ceiling, set_by, set_by_role, note, staff_id, training_id)
SELECT 'gpts900003', now(), now(), $1, 1, '', 'Program Lead', '[Go parity check]', pa.monitoring_staff_id, pa.training_course_id
FROM partner_assignment pa WHERE pa.id = 'gpts900002'`, fy); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM training_ceiling WHERE id = 'gpts900003'`); err != nil {
			t.Errorf("removing the test's ceiling: %v", err)
		}
	})

	found := false
	for _, row := range summaryTable(t, page).GetRows() {
		cells := row.GetCells()
		if cells[6].GetText() == "Partner Assigned — Awaiting Schedule" && cells[6].GetHref() == "/partner-oversight/" &&
			cells[7].GetText() == "No" && cells[8].GetText() == "Partner to schedule" {
			found = true
		}
	}
	if !found {
		t.Fatal("the hand-over filed for the test is not listed as awaiting the Partner")
	}

	staff := summaryTable(t, trainingSummaryOf(t, "pl1@edify.org", map[string]string{"view": "trainings", "tab": "staff"}))
	found = false
	for _, row := range staff.GetRows() {
		cells := row.GetCells()
		if cells[2].GetText() == "1" && cells[10].GetText() == "At ceiling" && cells[10].GetTone() == "success" &&
			cells[8].GetText() == "0" && cells[5].GetTone() == "warning" {
			found = true
		}
	}
	if !found {
		t.Fatalf("the Lead's own ceiling of 1 does not read At ceiling: %v", staff.GetRows())
	}
}
