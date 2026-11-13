package myplan

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
)

func TestADayOffMarksThePlannedDayTheTintAndTheCard(t *testing.T) {
	day := time.Date(2026, 11, 16, 0, 0, 0, 0, time.UTC)
	mark := &calendarpage.DayOffMark{Label: "Public holiday", Summary: "Mon 16 Nov · Public holiday"}
	label := "School Visit"
	held := &planRow{row: &row{a: &activity{id: "a1", plannedDate: &day, delivery: sp("staff")}, schoolName: "Hill School",
		schoolID: schoolID{value: "S1"}, activityTypeLabel: &label}, dayOff: mark, canPick: true, inTable: true}
	if got := held.dayOffFlag(); got != " Public holiday: reschedule" {
		t.Errorf("flag %q", got)
	}
	if got := pageRow(held, "Hill School", nil).GetTone(); got != "dayoff" {
		t.Errorf("tone %q, want dayoff", got)
	}
	// Done and overdue outrank the mark (_row_tone).
	held.rowState = "overdue"
	if got := pageRow(held, "Hill School", nil).GetTone(); got != "overdue" {
		t.Errorf("tone %q, want overdue", got)
	}
	plain := &planRow{row: &row{a: &activity{id: "a2"}}}
	if plain.dayOffFlag() != "" || pageRow(plain, "", nil).GetTone() != "" {
		t.Error("a row with no mark is marked")
	}

	// The card: a school's row ticked and linked by School ID; a meeting's
	// (named for its cluster, no School ID) plain; a row in no table with no
	// tick; nothing named reads "General".
	meeting := &planRow{row: &row{a: &activity{id: "a3"}, schoolName: "Cluster B", clusterID: "c1",
		clusterName: "Cluster B", activityTypeLabel: &label}, dayOff: mark}
	nothing := &planRow{row: &row{a: &activity{id: "a4"}, schoolName: "Unknown School", activityTypeLabel: &label}, dayOff: mark}
	table := dayOffCard([]*planRow{held, meeting, nothing}).GetTable()
	if table.GetTitle() != "Reschedule — On a Public Holiday or Leave Day" || !table.GetColumns()[4].GetNumeric() {
		t.Fatalf("card %v", table)
	}
	rows := table.GetRows()
	if c := rows[0].GetCells(); c[0].GetText() != "" || c[1].GetHref() != "/schools/S1" || c[3].GetText() != mark.Summary ||
		rows[0].GetPickLabel() != "Select School Visit at Hill School on 16 Nov 2026" {
		t.Errorf("school row %v", rows[0])
	}
	if c := rows[1].GetCells(); c[0].GetText() != dash || c[1].GetHref() != "" || rows[1].GetPickId() != "" {
		t.Errorf("meeting row %v", rows[1])
	}
	if got := rows[2].GetCells()[1].GetText(); got != "General" {
		t.Errorf("nothing named: %q", got)
	}
	// Work of no staff delivery: "The partner reschedules", not read.
	if got := rows[2].GetCells()[4].GetActions(); len(got) != 0 {
		t.Errorf("another delivery's actions %v", got)
	}
	if a := rows[0].GetCells()[4].GetActions()[0]; a.GetHref() != "/my-plan/a1/reschedule-drawer" || !a.GetPrimary() || a.GetKey() != "button" {
		t.Errorf("action %v", a)
	}
}
