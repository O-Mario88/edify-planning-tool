package planningoversight

import (
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
)

func TestPlainTeamQueryHandsOnWhatThisSliceDoesNotDraw(t *testing.T) {
	cases := []struct {
		name  string
		query url.Values
		want  bool
	}{
		{"the page as it opens", url.Values{}, true},
		{"the planning lens named", url.Values{"view": {"planning"}}, true},
		{"two views", url.Values{"view": {"planning", "coverage"}}, false},
		{"a period, a tab and a family", url.Values{"period": {"week"}, "owner": {"mine"}, "activity": {"visits"}}, true},
		{"an advanced filter", url.Values{"district_id": {"d1"}}, false},
		{"a blank advanced filter", url.Values{"risk": {"  "}}, true},
		{"the Export drawer's custom dates", url.Values{"start_date": {"2026-11-01"}}, false},
		{"a Country Director's follow-up", url.Values{"followup": {"f1"}}, false},
		{"a Unicode digit", url.Values{"month": {"١"}}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := plainTeamQuery(tc.query); got != tc.want {
				t.Fatalf("plainTeamQuery(%v) = %v, want %v", tc.query, got, tc.want)
			}
		})
	}
}

// team_planning_oversight_view's lens: a lens the reader lacks falls back
// to planning; the moved and redirected views are not this page's.
func TestActiveLensFallsBackAsTheViewDoes(t *testing.T) {
	lead := rules.TeamPlan.Readers[rules.TeamPlan.LeadRole]
	accountant := rules.TeamPlan.Readers["Accountant"]
	hr := rules.TeamPlan.Readers["HumanResources"]
	cases := []struct {
		name string
		r    Reader
		view string
		want string
	}{
		{"the page as it opens", lead, "", "planning"},
		{"stray spaces and capitals", lead, " PLANNING ", "planning"},
		{"a lens the Lead holds", lead, "coverage", "coverage"},
		{"a word the page does not know", lead, "nonsense", "planning"},
		{"a lens the Accountant lacks", accountant, "trainings", "planning"},
		{"the monitors, moved away", accountant, "monitor", ""},
		{"Special Projects, redirected", lead, "projects", ""},
		{"no planning lens", hr, "", "targets"},
	}
	for _, tc := range cases {
		q := url.Values{}
		if tc.view != "" {
			q.Set("view", tc.view)
		}
		if got := activeLens(tc.r, q); got != tc.want {
			t.Errorf("%s: lens %q, want %q", tc.name, got, tc.want)
		}
	}
}

func TestOwnerTabsChooseTheTabTheViewWould(t *testing.T) {
	members := []person{{id: "sp1", name: "Ann B.", ids: []string{"sp1", "u1"}}, {id: "sp2", name: "Cal D.", ids: []string{"sp2", "u2"}}}
	cases := []struct{ selected, want string }{
		{"", "team"},
		{"team", "team"},
		{"mine", "mine"},
		{"sp2", "sp2"},
		{"u1", "sp1"},    // a deep link's User id finds the officer's tab
		{"nope", "team"}, // anything else falls back to Whole team
	}
	for _, tc := range cases {
		tabs, key := ownerTabs(members, tc.selected)
		if key != tc.want {
			t.Errorf("ownerTabs(%q) = %q, want %q", tc.selected, key, tc.want)
		}
		if len(tabs) != 4 || tabs[0].Label != "Whole team" || tabs[1].Label != "My Work" || tabs[3].Label != "Cal D." {
			t.Fatalf("tabs = %+v", tabs)
		}
		active := 0
		for _, tab := range tabs {
			if tab.Active {
				active++
			}
		}
		if active != 1 {
			t.Errorf("ownerTabs(%q): %d active tabs", tc.selected, active)
		}
	}
}

func TestRosterForNarrowsToTheChosenPerson(t *testing.T) {
	roster := []person{{id: "lead", name: "Lead", ids: []string{"lead", "ul"}}, {id: "sp1", name: "Ann", ids: []string{"sp1", "u1"}}}
	cases := []struct {
		selected string
		want     int
	}{{"team", 2}, {"mine", 1}, {"sp1", 1}, {"stranger", 0}}
	for _, tc := range cases {
		if got := rosterFor(roster, tc.selected); len(got) != tc.want {
			t.Errorf("rosterFor(%q) = %d people, want %d", tc.selected, len(got), tc.want)
		}
	}
	if got := rosterFor(nil, "team"); got != nil {
		t.Errorf("no roster = %v, want none", got)
	}
}

func TestPeriodWordsAreThePagesOwn(t *testing.T) {
	if got := horizonLabel([]string{"2028", "2027"}); got != "FY 2027–2028" {
		t.Errorf("horizonLabel = %q", got)
	}
	if got := horizonLabel([]string{"2025"}); got != "FY 2025" {
		t.Errorf("horizonLabel = %q", got)
	}
	for week, want := range map[string]string{"2026-W46": "2026-11-09", "2026-W01": "2025-12-29", "2024-W40": "2024-09-30"} {
		if got := weekStart(week).Format("2006-01-02"); got != want {
			t.Errorf("weekStart(%s) = %s, want %s", week, got, want)
		}
	}
	// A week across 1 October reads both years (_plan_period).
	s := &Service{}
	years, label, read, err := s.planPeriod(nil, nil, partneroversight.Period{FY: "2027", Kind: "week", Week: "2026-W40"}, nil, time.Now())
	if err != nil || len(years) != 2 || years[0] != "2026" || years[1] != "2027" || label != "Week of 28 Sep 2026" || read.start.IsZero() {
		t.Errorf("week across the year: %v %q %+v %v", years, label, read, err)
	}
	if got := initials("Program Lead 2"); got != "PR" {
		t.Errorf("initials = %q", got)
	}
}

func TestTeamPageTonesOnlyAHelperLine(t *testing.T) {
	w := teamPlan{
		period:      partneroversight.Period{FY: "2027", Kind: "fy", Week: "2026-W46", Month: 11, Quarter: "Q1"},
		periodLabel: "FY 2027–2028", fyOptions: []string{"2026", "2027"}, activity: "visits",
		owner: "mine", panelName: "Program Lead 2", ownLabel: "Program Lead 2 (you)",
		reader: rules.TeamPlan.Readers[rules.TeamPlan.LeadRole],
	}
	w.tabs, _ = ownerTabs(nil, "mine")
	page := teamPage(w)
	for _, m := range page.GetBlocks()[2].GetStrip().GetMetrics() {
		if (m.Helper == "") != (m.Tone == "") {
			t.Errorf("%s: helper %q tone %q", m.Label, m.Helper, m.Tone)
		}
	}
	if got := page.GetHeader().GetActions()[0].GetHref(); got != "/team-planning-oversight/export-drawer?activity=visits&fy=2027&month=11&owner=mine&period=fy&quarter=Q1&week=2026-W46" {
		t.Errorf("export href = %s", got)
	}
	if got := page.GetBlocks()[4].GetSection(); got != "My Work" {
		t.Errorf("section = %q", got)
	}
}

// The Team Plan's period select shows the period in use, not always "week"
// (owner, 2026-11-13; intended.json go-fix-period-select-team-plan).
func TestTheTeamPlanPeriodSelectShowsThePeriodInUse(t *testing.T) {
	for _, kind := range []string{"week", "month", "quarter", "fy"} {
		block := teamFilters(teamPlan{period: partneroversight.Period{FY: "2027", Kind: kind, Quarter: "Q1", Month: 11}})
		if got := block.GetFilters().GetFilters()[0]; got.GetName() != "period" || got.GetValue() != kind {
			t.Fatalf("period %s: the select shows %q", kind, got.GetValue())
		}
	}
}
