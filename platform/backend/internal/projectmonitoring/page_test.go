package projectmonitoring

import (
	"errors"
	"testing"
	"time"
)

func day(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func f(x float64) *float64 { return &x }

func TestInterventionPlanKeepsTheLegacyPrimaryAndDropsGeneral(t *testing.T) {
	cases := []struct {
		name       string
		p          project
		primary    string
		supporting []string
		measured   bool
	}{
		{"legacy only", project{Intervention: "leadership"}, "leadership", nil, true},
		{"ordered targets", project{Targets: []string{"financial_health", "leadership"}}, "financial_health", []string{"leadership"}, true},
		{"legacy primary among targets", project{Intervention: "leadership", Targets: []string{"financial_health", "leadership"}}, "leadership", []string{"financial_health"}, true},
		{"general alone is not measured", project{Targets: []string{"general"}}, "", nil, false},
		{"no target at all is measured", project{}, "", nil, true},
		{"unknown codes are left out", project{Targets: []string{"nonsense", "general", "leadership"}}, "leadership", nil, true},
	}
	for _, c := range cases {
		primary, supporting := c.p.plan()
		if primary != c.primary || len(supporting) != len(c.supporting) || c.p.measuredBySSA() != c.measured {
			t.Errorf("%s: got %q %v %v", c.name, primary, supporting, c.p.measuredBySSA())
		}
		for i := range c.supporting {
			if supporting[i] != c.supporting[i] {
				t.Errorf("%s: supporting %v", c.name, supporting)
			}
		}
	}
}

func TestEnrolmentInterventionIsGeneralForAnUnmeasuredProject(t *testing.T) {
	e := enrolment{SupportArea: "some_area"}
	if got := enrolmentLabel(e, project{Targets: []string{"general"}}); got != rules.General {
		t.Fatalf("got %q", got)
	}
	if got := enrolmentLabel(e, project{Intervention: "leadership"}); got != "Some Area" {
		t.Fatalf("an unknown code is spaced and titled, got %q", got)
	}
	if got := enrolmentLabel(enrolment{}, project{Intervention: "leadership"}); got != "Leadership" {
		t.Fatalf("the project's primary target, got %q", got)
	}
}

func TestReadingTakesTheScoreAtEnrolmentAndTheLatestSince(t *testing.T) {
	history := []reading{{day(2025, 3, 1), 5.1}, {day(2025, 9, 1), 6.2}, {day(2026, 2, 1), 7.0}, {day(2026, 6, 1), 7.4}}
	r := readingOf("leadership", enrolment{}, day(2025, 9, 1), history, "")
	if *r.Baseline != 6.2 || *r.Latest != 7.4 || !r.LatestOn.Equal(day(2026, 6, 1)) || *r.change() != 1.2 {
		t.Fatalf("got %v %v %v", *r.Baseline, *r.Latest, *r.change())
	}
	// The enrolment's snapshot is the baseline of its matched intervention.
	r = readingOf("leadership", enrolment{Baseline: f(4.0)}, day(2025, 9, 1), history, "leadership")
	if *r.Baseline != 4.0 || *r.Latest != 7.4 {
		t.Fatalf("snapshot: got %v", *r.Baseline)
	}
	// Nothing before enrolment: every score is since.
	r = readingOf("leadership", enrolment{}, day(2024, 1, 1), history, "")
	if r.Baseline != nil || *r.Latest != 7.4 {
		t.Fatalf("no baseline: got %v", r.Baseline)
	}
	if r.Abbreviation != "LSHIP" || r.Label != "Leadership" {
		t.Fatalf("labels: %q %q", r.Abbreviation, r.Label)
	}
}

func TestImpactLabelFollowsTheEngineThenTheMissingEvidence(t *testing.T) {
	p := project{Intervention: "leadership"}
	cases := []struct {
		e    enrolment
		p    project
		want string
	}{
		{enrolment{Impact: "not_yet_measurable"}, p, "Window not open"},
		{enrolment{Impact: "improved"}, p, "Improved"},
		{enrolment{}, project{Targets: []string{"general"}}, "No focus set"},
		{enrolment{}, p, "Previous FY SSA missing"},
		{enrolment{Baseline: f(5)}, p, "Awaiting delivery"},
	}
	for _, c := range cases {
		if got := schoolRowOf(c.e, c.p, nil, nil, lens{}).ImpactLabel; got != c.want {
			t.Errorf("%+v: got %q, want %q", c.e, got, c.want)
		}
	}
}

func TestSchoolRowReadsItsScoresAndImprovement(t *testing.T) {
	e := enrolment{SchoolPK: "s1", CreatedAt: time.Date(2025, 9, 1, 22, 0, 0, 0, time.UTC)}
	readings := map[string]map[string][]reading{"s1": {"leadership": {{day(2025, 8, 1), 6.0}, {day(2026, 2, 1), 5.5}}}}
	r := schoolRowOf(e, project{Intervention: "leadership"}, map[string]string{}, readings, lens{})
	if score(r.Previous) != "6.0" || score(r.Current) != "5.5" || floatStr(*r.improvement()) != "-0.5" {
		t.Fatalf("got %s %s", score(r.Previous), score(r.Current))
	}
	if r.AddedBy != "—" || dayLabel(e.enrolledOn()) != "1 Sep 2025" {
		t.Fatalf("got %q %q", r.AddedBy, dayLabel(e.enrolledOn()))
	}
	facts := details(r)
	if facts[2].Label != "LSHIP" || facts[2].Value != "6.0 → 5.5 (-0.5)" {
		t.Fatalf("details: %v", facts[2])
	}
}

func TestStageAndColumnFiltersOnASchoolNobodyPlanned(t *testing.T) {
	r := schoolRow{e: enrolment{District: "Mukono"}, Purpose: "Pilot"}
	cases := []struct {
		stage string
		picks map[string]string
		want  bool
	}{
		{"", nil, true},
		{"not_planned", nil, true},
		{"none", nil, true},
		{"staff_planned", nil, false},
		{"delivered", nil, false},
		{"", map[string]string{"district": "Mukono"}, true},
		{"", map[string]string{"district": "Wakiso"}, false},
		{"", map[string]string{"purpose": "Pilot"}, true},
		{"", map[string]string{"partner": "Anyone"}, false},
	}
	for _, c := range cases {
		if got := r.matches(c.stage, c.picks); got != c.want {
			t.Errorf("%q %v: got %v", c.stage, c.picks, got)
		}
	}
}

func TestWhatThisPieceDoesNotDrawIsPassedOn(t *testing.T) {
	many := make([]schoolRow, rules.PageSize+1)
	for _, c := range []projectRow{{impact: impact{Cohort: 1}}, {rows: many}} {
		if _, err := (view{projects: []projectRow{c}}).choose(""); !errors.Is(err, errUnread) {
			t.Errorf("got %v", err)
		}
	}
	if _, err := (view{projects: []projectRow{{rows: many[:rules.PageSize]}}}).choose(""); err != nil {
		t.Errorf("one full page is drawn: %v", err)
	}
}

func TestActionsByReader(t *testing.T) {
	r := schoolRow{e: enrolment{ID: "e1"}}
	if c := actions(view{fy: "2027"}, r); c.GetText() != "View" || len(c.GetActions()) != 0 {
		t.Fatalf("a watcher with no door reads View: %v", c)
	}
	r.LeaveURL = "/projects/capacity/withdraw?enrolment=e1"
	c := actions(view{fy: "2027", l: lens{controls: true}}, r)
	if c.GetText() != pausedNote || len(c.GetActions()) != 2 || c.GetActions()[0].GetHref() != "/projects/monitoring/school?enrolment=e1&fy=2027" {
		t.Fatalf("a paused project's coordinator: %v", c)
	}
	r.ScheduleURL, r.PartnerURL = "/s", "/p"
	if c := actions(view{l: lens{controls: true}}, r); len(c.GetActions()) != 4 || c.GetActions()[3].GetKey() != "danger" {
		t.Fatalf("the coordinator: %v", c)
	}
}

func TestFormatting(t *testing.T) {
	if horizonLabel([]string{"2027", "2028"}) != "FY 2027–2028" || horizonLabel([]string{"2026"}) != "FY 2026" || horizonLabel(nil) != "" {
		t.Fatal("horizon label")
	}
	if intcomma(1234567) != "1,234,567" || intcomma(12) != "12" || floatStr(7) != "7.0" || pyTitle("o'neil area") != "O'Neil Area" {
		t.Fatal("python formatting")
	}
	got := sortedFold(map[string]bool{"wakiso": true, "Mukono": true, "Busia": true})
	if got[0] != "Busia" || got[1] != "Mukono" || got[2] != "wakiso" {
		t.Fatalf("casefold order: %v", got)
	}
	if plural(1) != "" || plural(0) != "s" {
		t.Fatal("pluralize")
	}
}
