package myplan

import (
	"strings"
	"testing"
)

func TestListRowMenuFollowsListActions(t *testing.T) {
	all := ListDoors{Schedule: true, Assign: true, Withdraw: true, Move: true}
	labels := func(r listRow, d ListDoors) (string, string) {
		row, ok := r.pageRow(d)
		if !ok {
			return "no menu", ""
		}
		var out []string
		for _, a := range row.Cells[8].Actions {
			out = append(out, a.Key+":"+a.Label)
		}
		return strings.Join(out, ", "), row.PickId
	}
	cases := []struct {
		name     string
		row      listRow
		doors    ListDoors
		want     string
		wantPick string
	}{
		{"an open school", listRow{school: ListSchool{ID: "s1", Code: "1001", CanAssign: true}}, all,
			"menu:Schedule, menu:Assign to partner, menu:Open school", "1001"},
		{"a school Assign is shut for", listRow{school: ListSchool{ID: "s1", Code: "1001"}}, all,
			"menu:Schedule, menu:Open school", ""},
		{"one staff activity", listRow{school: ListSchool{ID: "s1"}, activities: []string{"a1"}}, all,
			"menu:Schedule, menu:Reschedule, danger:Cancel staff activity, menu:Open school", "s1"},
		{"two staff activities and a hand-over", listRow{school: ListSchool{ID: "s1", Code: "7"}, activities: []string{"a1", "a2"}, withdraw: "pa1"}, all,
			"menu:Schedule, menu:Reschedule 2 activities, danger:Cancel 2 staff activities, danger:Withdraw from Partner, menu:Open school", "7"},
		{"a reader offered nothing", listRow{school: ListSchool{ID: "s1"}}, ListDoors{}, "no menu", ""},
	}
	for _, c := range cases {
		got, pick := labels(c.row, c.doors)
		if got != c.want || pick != c.wantPick {
			t.Errorf("%s: menu %q pick %q, want %q pick %q", c.name, got, pick, c.want, c.wantPick)
		}
	}
}

func TestListCellsReadTheSchoolsYear(t *testing.T) {
	sc := ListSchool{StaffVisits: 2, HasPartner: true, NeedsTraining: false}
	if c := listVisitCell(sc); c.Text != "2 staff + Partner" || c.Tone != "info" {
		t.Errorf("visit cell = %q %q", c.Text, c.Tone)
	}
	if c := listTrainingCell(sc); c.Text != "Not required" || c.Tone != "" {
		t.Errorf("training cell = %q %q", c.Text, c.Tone)
	}
	if c := listTrainingCell(ListSchool{NeedsTraining: true, Meeting: true}); c.Text != "Cluster meeting only" || c.Tone != "warning" {
		t.Errorf("meeting-only training cell = %q %q", c.Text, c.Tone)
	}
}
