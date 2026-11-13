package clusterpage

import (
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

func pillsOf(p []*screensv1.PageBadge) [][4]string {
	out := [][4]string{}
	for _, b := range p {
		out = append(out, [4]string{b.GetText(), b.GetTone(), b.GetTitle(), b.GetIcon()})
	}
	return out
}

// Each chip is one pill in the page's own planning tone, in order, across
// the lists a cell joins (the Training cell's trainings, then its meetings).
func TestChipPillsKeepEachChipsToneInOrder(t *testing.T) {
	got := pillsOf(ChipPills(
		[]schoolplanning.Chip{{Label: "1 Planned", Tone: "planned"}, {Label: " 1  Verified ", Tone: "verified"}},
		[]schoolplanning.Chip{{Label: "1 Meeting Planned", Tone: "planned"}},
	))
	want := [][4]string{{"1 Planned", "planned", "", ""}, {"1 Verified", "verified", "", ""}, {"1 Meeting Planned", "planned", "", ""}}
	if len(got) != len(want) {
		t.Fatalf("pills = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("pill %d = %v, want %v", i, got[i], want[i])
		}
	}
	if ChipPills() != nil {
		t.Error("no chips must give no pills")
	}
}

// visit_lock_cell.html: an unlocked visit is the outlined chip with an open
// padlock and no sentence; a held one the grey chip, a shut padlock and the
// gate's staff sentence; a school the lock does not apply to has no chip.
func TestLockPillsFollowTheVisitLockCell(t *testing.T) {
	rules := visitgate.Rules{
		LockLabels:        map[string]string{"unlocked": "Unlocked", "staff_visit_scheduled": "Staff visit scheduled", "not_applicable": ""},
		OutreachOnlyTypes: []string{"Champion"},
	}
	open := visitgate.Gate{StaffCanSchedule: true, School: visitgate.School{Type: "Client"}}
	held := visitgate.Gate{StaffCanSchedule: false, Rule: "client", School: visitgate.School{Type: "Client"},
		StaffReason: "Kasawo has had its staff support visit for FY2027 (1/1)."}
	champion := visitgate.Gate{StaffCanSchedule: true, School: visitgate.School{Type: "Champion"}}

	cases := []struct {
		name string
		gate visitgate.Gate
		want [][4]string
	}{
		{"unlocked", open, [][4]string{{"Unlocked", "open", "", "unlock"}}},
		{"held", held, [][4]string{{"Staff visit scheduled", "closed", "Kasawo has had its staff support visit for FY2027 (1/1).", "lock"}}},
		{"not applicable", champion, [][4]string{}},
	}
	for _, c := range cases {
		got := pillsOf(LockPills(c.gate, rules))
		if len(got) != len(c.want) || (len(got) == 1 && got[0] != c.want[0]) {
			t.Errorf("%s: pills = %v, want %v", c.name, got, c.want)
		}
	}
}

// partials/clusters/filters.html authors SSA status, Cluster risk and
// Activity status under its own More filters; the rest share the row.
func TestTheLastThreeFiltersAreFoldedUnderMore(t *testing.T) {
	block := filters(filterState{fy: "2027"}, []string{"2027"}, nil, nil, nil)
	got := map[string]bool{}
	for _, f := range block.GetFilters().GetFilters() {
		got[f.GetName()] = f.GetMore()
	}
	want := map[string]bool{"fy": false, "quarter": false, "district": false, "sub_county": false, "staff": false,
		"ssa_status": true, "cluster_risk": true, "activity_status": true}
	for name, more := range want {
		if got[name] != more {
			t.Errorf("%s more = %v, want %v", name, got[name], more)
		}
	}
}
