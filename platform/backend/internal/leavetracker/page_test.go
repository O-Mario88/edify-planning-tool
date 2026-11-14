package leavetracker

import (
	"strings"
	"testing"
)

func TestAHeatmapRowReadsRoleBesideTheFirstWeekAndSkipsLocks(t *testing.T) {
	heat := []HeatRow{{StaffID: "s1", Name: "Mary A.", Role: "CCEO", Weeks: []HeatWeek{
		{Status: "On Leave", Activities: 1}, {Status: "Available"}, {Status: "Blocked", Activities: 3}, {Status: "High Workload", Activities: 6}}}}
	items := heatPanel(heat).GetPanel().Items
	if len(items) != 4 {
		t.Fatalf("items: %v", items)
	}
	if l := items[0].GetLinks().Links[0]; l.Href != "/staff/s1" || l.Text != "Mary A." {
		t.Errorf("link: %v", l)
	}
	if r := items[1].GetRows().Rows[0]; r.Label != "CCEO" || r.Value != "1" {
		t.Errorf("first week: %v", r)
	}
	if items[2].GetText() != "0" || items[3].GetText() != "6" {
		t.Errorf("weeks: %v %v", items[2], items[3])
	}
}

func TestHandoverNotesTruncateAsTheTemplateDoes(t *testing.T) {
	long := strings.Repeat("a", 130)
	if got := truncate(long, noteChars); len([]rune(got)) != 120 || !strings.HasSuffix(got, "…") {
		t.Errorf("truncate: %q", got)
	}
	if truncate("short", noteChars) != "short" || initials("mary") != "MA" || initials("") != "" {
		t.Error("short values")
	}
}
