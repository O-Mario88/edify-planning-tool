package clusterpage

import (
	"slices"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func f(v float64) *float64 { return &v }

func s(v string) *string { return &v }

// A cluster that has met, is fully assessed, visited and trained.
func onTrack() planning {
	return planning{Schools: 4, WithSSA: 4, MeetingsDone: 1}
}

func TestTheRiskFollowsTheExistingOrder(t *testing.T) {
	cases := []struct {
		name string
		avg  *float64
		plan planning
		want string
	}{
		{"an average under 5", f(4.9), onTrack(), "critical"},
		{"under half the schools assessed", f(8), planning{Schools: 4, WithSSA: 1, MeetingsDone: 1}, "critical"},
		{"no meeting held", f(8), planning{Schools: 4, WithSSA: 4}, "critical"},
		{"an average under 6", f(5.9), onTrack(), "needs_attention"},
		{"schools not visited", nil, planning{Schools: 4, WithSSA: 4, MeetingsDone: 1, NotVisited: 1}, "needs_attention"},
		{"schools not trained", f(7), planning{Schools: 4, WithSSA: 2, MeetingsDone: 1, NotTrained: 2}, "needs_attention"},
		{"on track", f(6), onTrack(), "healthy"},
		{"no schools and no assessment", nil, planning{MeetingsDone: 2}, "healthy"},
	}
	for _, c := range cases {
		if got := (card{avgSSA: c.avg, plan: c.plan}).risk(); got != c.want {
			t.Errorf("%s: %s, want %s", c.name, got, c.want)
		}
	}
}

func TestTheWeakestAreTheLowestFourWithTiesByTheirValue(t *testing.T) {
	c := card{stats: map[string]stat{
		"leadership":           {avg: 4.0},
		"enrolment":            {avg: 4.04}, // rounds to 4.0, ties with leadership
		"financial_health":     {avg: 6.1},
		"christlike_behaviour": {avg: 3.2},
		"teaching_environment": {avg: 5.0},
		"learning_environment": {avg: 9.0},
	}}
	got := []string{}
	for _, w := range c.weakest() {
		got = append(got, w.intervention)
	}
	want := []string{"christlike_behaviour", "enrolment", "leadership", "teaching_environment"}
	if !slices.Equal(got, want) {
		t.Fatalf("weakest %v, want %v", got, want)
	}
	if len((card{stats: map[string]stat{}}).weakest()) != 0 {
		t.Fatal("a cluster with no scores ranks nothing")
	}
}

func TestPagesAreElidedAsDjangoElidesThem(t *testing.T) {
	cases := []struct {
		number, pages int
		want          []int
	}{
		{1, 3, []int{1, 2, 3}},
		{2, 4, []int{1, 2, 3, 4}},
		{1, 5, []int{1, 2, 0, 5}},
		{3, 5, []int{1, 2, 3, 4, 5}},
		{5, 5, []int{1, 0, 4, 5}},
		{5, 9, []int{1, 0, 4, 5, 6, 0, 9}},
	}
	for _, c := range cases {
		if got := elided(c.number, c.pages); !slices.Equal(got, c.want) {
			t.Errorf("page %d of %d: %v, want %v", c.number, c.pages, got, c.want)
		}
	}
}

func TestAPageNumberIsReadAsPythonReadsIt(t *testing.T) {
	cases := map[string]int{"": 1, "2": 2, " 3 ": 3, "+2": 2, "1_0": 3, "abc": 1, "2.0": 1, "0": 3, "-1": 3, "99": 3, "1__0": 1}
	for in, want := range cases {
		if got, _ := pageOf(in, 12); got != want {
			t.Errorf("page %q of 12 clusters: %d, want %d", in, got, want)
		}
	}
	if number, pages := pageOf("4", 0); number != 1 || pages != 1 {
		t.Errorf("no clusters: page %d of %d, want 1 of 1", number, pages)
	}
}

func TestSharesRoundHalfToEven(t *testing.T) {
	for _, c := range []struct{ n, total, want int }{{1, 8, 12}, {3, 8, 38}, {1, 3, 33}, {2, 3, 67}, {14, 15, 93}, {0, 0, 0}} {
		if got := percentOf(c.n, c.total); got != c.want {
			t.Errorf("%d of %d: %d%%, want %d%%", c.n, c.total, got, c.want)
		}
	}
}

func TestFiguresAreWrittenAsThePageWritesThem(t *testing.T) {
	for in, want := range map[float64]string{71.4: "71.4", 100: "100.0", 33.3: "33.3", 50: "50.0"} {
		if got := pyFloat(in); got != want {
			t.Errorf("str(%v) = %s, want %s", in, got, want)
		}
	}
	for in, want := range map[float64]string{5: "5", 4.8: "4.8", 10: "10", 0.5: "0.5"} {
		if got := scoreText(in); got != want {
			t.Errorf("floatformat(%v, -1) = %s, want %s", in, got, want)
		}
	}
	if got := thousands(1234567); got != "1,234,567" {
		t.Errorf("thousands %s", got)
	}
}

func TestACardNamesItsPlaceLeaderAndFacilitator(t *testing.T) {
	day := time.Date(2026, 4, 22, 0, 0, 0, 0, time.UTC)
	c := card{
		cluster: cluster{ID: "c1", Name: " Cluster   A ", District: s("Mukono"), Covered: []string{"Goma", "Kasawo"},
			LeaderName: "  Jane  Nakato ", LeaderPhone: ""},
		schools: 7, staff: 1, avgSSA: f(5.5), lastMeeting: &day, meetingsFY: 2,
		plan:  planning{Schools: 8, WithSSA: 5, Baseline: 2, Cleanup: 7, Ready: 5, MeetingsDone: 1},
		stats: map[string]stat{},
	}
	r := record(c, Doors{Page: true, Plan: false, AddSchools: true}, "2027")
	got := map[string][2]string{}
	for _, fact := range r.GetFacts() {
		got[fact.GetLabel()] = [2]string{fact.GetValue(), fact.GetTone()}
	}
	want := map[string][2]string{
		"Location": {"Mukono, Goma, Kasawo", ""}, "Cluster Leader": {"Jane Nakato", ""},
		"Cluster Leader Phone": {"Not Entered", ""}, "Facilitated by": {"Staff", ""},
		"Avg SSA": {"5.5/10", "caution"}, "Last Meeting": {"22 Apr 2026", ""}, "Last Training": {"Never", ""},
		"SSA Coverage": {"5/7 (62.5%)", ""}, "Without SSA": {"3 schools", "caution"},
		"SSA Required": {"2", "alert"}, "Ready for Planning": {"5", "good"}, "Next Action": {"Monitor progress", ""},
	}
	for label, w := range want {
		if got[label] != w {
			t.Errorf("%s: %v, want %v", label, got[label], w)
		}
	}
	if r.GetTitle() != "Cluster A" || r.GetHref() != "/clusters/c1" || r.GetBadges()[0].GetText() != "Needs Attention" {
		t.Errorf("title %q href %q badge %q", r.GetTitle(), r.GetHref(), r.GetBadges()[0].GetText())
	}
	if len(r.GetActions()) != 1 || r.GetActions()[0].GetLabel() != "Add Schools" {
		t.Errorf("a role that may add schools but not plan gets Add Schools alone: %v", r.GetActions())
	}
	items := r.GetDetails()[0].GetPanel().GetItems()
	if len(items) != 2 || items[1].GetText() != "No confirmed SSA scores are available yet." {
		t.Errorf("a cluster with no scores says so: %v", items)
	}
}

func TestTheSubCountyFallsBackInTheExistingOrder(t *testing.T) {
	cases := []struct {
		c    cluster
		want string
	}{
		{cluster{Covered: []string{"A", "B"}, SubCounty: s("C")}, "A, B"},
		{cluster{SubCounty: s(""), SubCountyName: "D"}, ""},
		{cluster{SubCountyName: "D"}, "D"},
		{cluster{}, "District-level cluster"},
	}
	for _, c := range cases {
		if got := c.c.subCountyLine(); got != c.want {
			t.Errorf("%+v: %q, want %q", c.c, got, c.want)
		}
	}
	if (cluster{}).districtLine() != "Unknown" {
		t.Error("a cluster with no district reads Unknown")
	}
}

func TestAnEmptyListHasNoneForItsWeakestAndAnAverageOfNothing(t *testing.T) {
	metrics := stripBlock(nil).GetStrip().GetMetrics()
	byLabel := map[string]*screensv1.PageMetric{}
	for _, m := range metrics {
		byLabel[m.GetLabel()] = m
	}
	if m := byLabel["Weakest Intervention"]; m.GetValue() != "None" || m.GetNote() != "Avg 0.0" {
		t.Errorf("weakest %q note %q", m.GetValue(), m.GetNote())
	}
	if m := byLabel["Average Cluster SSA"]; m.GetValue() != "0.0" || m.GetNote() != "Out of 10.0" {
		t.Errorf("average %q note %q", m.GetValue(), m.GetNote())
	}
	if m := byLabel["Without Current SSA"]; m.GetHelper() != "0% of total" {
		t.Errorf("share %q", m.GetHelper())
	}
}

func TestTheFiguresFilterKeepsWhatThePageKeeps(t *testing.T) {
	done := card{schools: 3, plan: planning{Schools: 3, WithSSA: 3, MeetingsOpen: 1}}
	partial := card{schools: 3, plan: planning{Schools: 4, WithSSA: 2, MeetingsDone: 1}}
	all := []card{done, partial}
	if got := keep(all, filterState{ssaStatus: "done"}); len(got) != 1 || got[0].plan.WithSSA != 3 {
		t.Errorf("complete: %v", got)
	}
	if got := keep(all, filterState{ssaStatus: "not_done"}); len(got) != 1 || got[0].plan.WithSSA != 2 {
		t.Errorf("incomplete: %v", got)
	}
	if got := keep(all, filterState{activity: "pending"}); len(got) != 1 || got[0].plan.MeetingsOpen != 1 {
		t.Errorf("pending: %v", got)
	}
	if got := keep(all, filterState{activity: "completed"}); len(got) != 1 || got[0].plan.MeetingsDone != 1 {
		t.Errorf("completed: %v", got)
	}
	if got := keep(all, filterState{ssaStatus: "anything"}); len(got) != 2 {
		t.Errorf("an unknown value filters nothing: %v", got)
	}
}

func TestOnlyTheRolesTheExistingGateLetsInOpenThePage(t *testing.T) {
	for role, open := range map[string]bool{
		"CCEO": true, "Program Lead": true, "Admin": true, "CountryDirector": true, "ImpactAssessment": true,
		"ProjectCoordinator": false, "BusinessTransformationOfficer": false, "PartnerAdmin": false, "Accountant": false,
	} {
		if rules.Doors[role].Page != open {
			t.Errorf("%s opens the page: %v, want %v", role, rules.Doors[role].Page, open)
		}
	}
}

func TestABadgeCellReadsItsChipsAsTheFeedDoes(t *testing.T) {
	got := joinedChips([]schoolplanning.Chip{{Label: "1 Planned"}, {Label: "2 Complete"}}, []schoolplanning.Chip{{Label: "1 Cluster Meeting Planned"}})
	if got != "1 Planned2 Complete1 Cluster Meeting Planned" {
		t.Errorf("cell %q", got)
	}
}

func TestASchoolRowOffersOnlyTheDoorsThatOpen(t *testing.T) {
	sc := listedSchool{ID: "s1", Code: "1546", Name: "Kasawo Primary", Enrolment: 0}
	sc.gate.CanAssignPartner = false
	doors := Doors{Schedule: true, AssignPartner: true, BulkSchedule: false, OpenSchool: false}
	row := schoolRow(clusterRef{id: "c1", name: "Cluster A"}, sc, nil, true, nil, true, doors, schoolprofile.GateRules(), false)
	actions := row.GetCells()[len(row.GetCells())-1].GetActions()
	if len(actions) != 1 || actions[0].GetLabel() != "Schedule" {
		t.Errorf("a school the gate keeps from partners, read by a role that cannot plan sessions: %v", actions)
	}
	if row.GetCells()[1].GetHref() != "" || row.GetDetailsHref() != "" {
		t.Error("a reader who may not open profiles gets no links")
	}
	if row.GetPickId() != "" {
		t.Error("no tick box where nothing can be done to the ticked schools")
	}
	facts := map[string][2]string{}
	for _, f := range row.GetDetails() {
		facts[f.GetLabel()] = [2]string{f.GetValue(), f.GetTone()}
	}
	for label, want := range map[string][2]string{
		"District": {"—", ""}, "Staff Name": {"Unassigned", ""}, "SSA": {"Not assessed", ""},
		"Last Visit": {"Never", "alert"}, "Enrollment": {"0", ""}, "Next Activity": {"—", ""}, "Cluster": {"Cluster A", ""},
	} {
		if facts[label] != want {
			t.Errorf("%s: %v, want %v", label, facts[label], want)
		}
	}
	planner := Doors{Schedule: true, AssignPartner: true, BulkSchedule: true, OpenSchool: true}
	sc.gate.CanAssignPartner = true
	row = schoolRow(clusterRef{id: "c1"}, sc, nil, true, nil, true, planner, schoolprofile.GateRules(), true)
	got := []string{}
	for _, a := range row.GetCells()[len(row.GetCells())-1].GetActions() {
		got = append(got, a.GetLabel())
	}
	if !slices.Equal(got, []string{"Schedule", "Assign", "Add to Meeting", "Add to Training"}) || row.GetPickId() != "1546" {
		t.Errorf("a planner at a partner-supported school: %v, pick %q", got, row.GetPickId())
	}
}
