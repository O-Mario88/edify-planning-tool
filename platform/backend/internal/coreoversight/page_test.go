package coreoversight

import (
	"context"
	"errors"
	"math"
	"net/url"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestOnlyThePageItselfIsAnsweredAndOnlyForItsRoles(t *testing.T) {
	s := NewService(nil, time.Now)
	for _, tc := range []struct {
		path, role string
		served     bool
		refused    bool
	}{
		{"/core-schools-oversight", "CCEO", true, true},
		{"/core-schools-oversight/xyz", "CCEO", true, true},
		{"/core-schools-oversight/export", "Admin", true, true},
		{"/core-schools", "CCEO", false, false},
		{"/cluster-oversight/", "CCEO", false, false},
		{Path, "Accountant", true, true},
		{Path, "ProjectCoordinator", true, true},
		{Path, "BusinessTransformationOfficer", true, true},
		{Path, "NoSuchRole", true, true},
	} {
		_, served, err := s.Build(context.Background(), auth.Principal{ActiveRole: tc.role}, tc.path, url.Values{})
		if served != tc.served || errors.Is(err, ErrNotAvailable) != tc.refused {
			t.Errorf("%s as %s: served %v, err %v", tc.path, tc.role, served, err)
		}
	}
}

// The two tabs of planned work are My Plan's tables and stay the existing
// application's; they are passed on before anything is read.
func TestThePlannedWorkTabsAreLeftToTheExistingApplication(t *testing.T) {
	s := NewService(nil, time.Now)
	for _, tab := range []string{"core_visits", "core_trainings", " core_visits "} {
		_, served, err := s.Build(context.Background(), auth.Principal{ActiveRole: "CCEO"}, Path, url.Values{"tab": {tab}})
		if served || err != nil {
			t.Errorf("tab %q: served %v, err %v", tab, served, err)
		}
	}
}

func TestEveryRoleThatOpensThePageIsOneTheExportNames(t *testing.T) {
	for _, role := range []string{"CCEO", "Program Lead", "CountryDirector", "RegionalVicePresident", "RegionalProgramLead", "ImpactAssessment", "Admin"} {
		if !rules.Doors[role].Page {
			t.Errorf("%s does not open the page", role)
		}
	}
	if rules.Doors["RegionalVicePresident"].School || rules.Doors["RegionalVicePresident"].Review {
		t.Error("a Regional Vice President is given school links or the Champion review")
	}
}

// ChampionEligibilityService.scan keeps a school's live plan of the running
// year over a newer or older one, else its newest.
func TestTheLivePlanIsTheRunningYearsElseTheNewest(t *testing.T) {
	r := &records{
		ScanProfiles: []string{"A", "B"},
		ScanPlans: []scanPlanRow{
			{Code: "A", FY: "2028", Total: 8, Completed: 0}, {Code: "A", FY: "2027", Total: 8, Completed: 8},
			{Code: "B", FY: "2026", Total: 8, Completed: 8}, {Code: "B", FY: "2025", Total: 8, Completed: 0},
		},
		ScanSSAs:    []scanSSARow{{ID: "a1", Code: "A", Average: ptr(9.0)}, {ID: "b1", Code: "B", Average: ptr(9.0)}},
		ScanScores:  []scanScoreRow{{RecordID: "a1", Score: ptr(8.0)}, {RecordID: "b1", Score: ptr(8.0)}},
		ScanSchools: []scanSchoolRow{{Code: "A"}, {Code: "B"}},
	}
	judged := scan(r, "2027")
	if !judged["A"].eligible {
		t.Error("the running year's complete plan should speak for A")
	}
	if !judged["B"].eligible {
		t.Error("B's newest plan should speak for it")
	}
}

func TestTheChampionScoreIsTheOfficialFormula(t *testing.T) {
	for _, tc := range []struct {
		name                             string
		earliest, latest                 float64
		scores                           []float64
		slots, done, closed, clean, ssas int
		want                             float64
		eligible                         bool
	}{
		// 8.5/10*40 + (1.5/3)*25 + 15 + 10 + 5 + 5.
		{"a candidate", 7.0, 8.5, []float64{7.5, 9}, 8, 8, 0, 0, 2, 81.5, true},
		// No scores: nothing balances; one SSA sustains half; no slots; a
		// quarter of the closed work has clean evidence (52.75, to even).
		{"nothing yet", 0, 6.0, nil, 0, 0, 4, 1, 1, 52.8, false},
		{"an area below 7", 5, 9, []float64{6.99, 9}, 8, 8, 2, 2, 3, 96, false},
	} {
		m := scoreValues(tc.earliest, tc.latest, tc.scores, tc.slots, tc.done, tc.closed, tc.clean, tc.ssas)
		if m.score != tc.want || m.eligible != tc.eligible {
			t.Errorf("%s: %v %v, want %v %v", tc.name, m.score, m.eligible, tc.want, tc.eligible)
		}
	}
}

func TestADecimalScoreIsWrittenToOnePlaceHalfUp(t *testing.T) {
	for in, want := range map[string]string{"6.10": "6.1", "4.25": "4.3", "7.05": "7.1", "0.04": "0.0", "-0.04": "0.0", "-1.25": "-1.3", "10": "10.0"} {
		if got := decimalOne(in); got != want {
			t.Errorf("%s: %s, want %s", in, got, want)
		}
	}
}

func TestFiguresReadAsThePageWritesThem(t *testing.T) {
	for _, tc := range []struct{ got, want string }{
		{floatStr(5.0), "5.0"}, {floatStr(5.83), "5.83"}, {signedFloat(0.5), "+0.5"}, {signedFloat(math.Copysign(0, -1)), "-0.0"},
		{signedInt(0), "0"}, {signedInt(3), "+3"}, {interventionLabel("new_area_2028"), "New Area 2028"},
	} {
		if tc.got != tc.want {
			t.Errorf("%q, want %q", tc.got, tc.want)
		}
	}
}

func TestTheTablesPageIsANumberFromOneUpClampedToThePagesThereAre(t *testing.T) {
	for _, tc := range []struct {
		asked string
		total int
		want  int
	}{{"", 141, 1}, {"2", 141, 2}, {" 3 ", 141, 3}, {"99", 141, 3}, {"0", 141, 1}, {"-1", 141, 1}, {"two", 141, 1}, {"2", 10, 1}} {
		if got, _ := pageNumber(tc.asked, tc.total); got != tc.want {
			t.Errorf("page %q of %d: %d, want %d", tc.asked, tc.total, got, tc.want)
		}
	}
	if got := window(4, 9); len(got) != 7 || got[1] != 0 || got[5] != 0 {
		t.Errorf("window(4, 9) = %v", got)
	}
}

// A one-word heading and its count are read as one word, which the feed
// does not draw; two words are.
func TestAOneWordHeadingIsNotDrawn(t *testing.T) {
	if got := listSection("Champion", 3, items{}); len(got) != 1 {
		t.Errorf("Champion: %d blocks", len(got))
	}
	if got := listSection("Not Yet Ready", 0, items{}); len(got) != 2 {
		t.Errorf("Not Yet Ready: %d blocks", len(got))
	}
}

func TestALabelFollowedByAFigureIsADataRow(t *testing.T) {
	got := paired([]*screensv1.PagePanelItem{textItem("Escalations"), textItem("12"), textItem("Open"), textItem("—"), textItem("3")})
	if len(got) != 2 || len(got[0].GetRows().GetRows()) != 2 || got[1].GetText() != "3" {
		t.Errorf("%v", got)
	}
}

func TestAFilterIsReadStrippedButShownAsSent(t *testing.T) {
	rows := []*school{{name: "A", district: "Mukono", trajectory: "declined"}, {name: "B", district: "Jinja", trajectory: "improved"}}
	q := url.Values{"district": {" Mukono "}, "trajectory": {" declined "}}
	if got := filtered(rows, q); len(got) != 1 || got[0].name != "A" {
		t.Errorf("%v", got)
	}
	block := filterBlock(newView(q, "2027", []string{"2027"}), rows).GetFilters()
	for _, f := range block.GetFilters() {
		if (f.GetName() == "district" || f.GetName() == "trajectory") && f.GetValue() != "" {
			t.Errorf("%s shown as %q", f.GetName(), f.GetValue())
		}
	}
}
