package schooldirectory

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func f(v float64) *float64 { return &v }

func TestScoresFallInTheExistingBands(t *testing.T) {
	cases := []struct {
		score      *float64
		band, tone string
	}{
		{nil, "No SSA", "neutral"}, {f(10), "Strong", "perfect"}, {f(9.9), "Strong", "success"},
		{f(8), "Strong", "success"}, {f(7.9), "Improving", "lime"}, {f(6), "Improving", "lime"},
		{f(5.9), "Warning", "warning"}, {f(5), "Warning", "warning"}, {f(4.9), "Critical", "danger"},
	}
	for _, c := range cases {
		if band, tone := ssaBand(c.score); band != c.band || tone != c.tone {
			t.Errorf("%v: %s %s, want %s %s", c.score, band, tone, c.band, c.tone)
		}
	}
}

func TestTheAverageIsAddedAndRoundedAsPythonDoes(t *testing.T) {
	// A school's eight scores whose true average is 6.85: plain addition
	// lands above it and rounds to 6.9; Python's compensated sum lands below
	// and rounds to 6.8, which is what the existing page shows.
	scores := []float64{7.3, 7, 7.6, 5, 7, 7.7, 6.6, 6.6}
	if got := pyRound1(pySum(scores) / 8); got != 6.8 {
		t.Fatalf("average %v, want 6.8", got)
	}
	for in, want := range map[float64]float64{6.25: 6.2, 6.35: 6.3, 6.45: 6.5, 7.05: 7.0, 5.0: 5.0, 2.0 / 3.0: 0.7} {
		if got := pyRound1(in); got != want {
			t.Errorf("round(%v, 1) = %v, want %v", in, got, want)
		}
	}
}

func TestScoresAreGroupedInTheInterventionOrder(t *testing.T) {
	summary := summarize([]struct {
		intervention string
		score        *float64
	}{
		{"enrolment", f(4)}, {"christlike_behaviour", f(8)}, {"leadership", f(6)}, {"financial_health", nil},
		{"exposure_to_word_of_god", f(7)},
	})
	if summary.average == nil || *summary.average != 6.2 || summary.tone != "lime" {
		t.Fatalf("average %v tone %s", summary.average, summary.tone)
	}
	// urgent, performing-well, warning
	if len(summary.groups[0]) != 1 || summary.groups[0][0].code != "enrolment" {
		t.Fatalf("urgent: %+v", summary.groups[0])
	}
	if well := summary.groups[1]; len(well) != 2 || well[0].code != "christlike_behaviour" || well[1].code != "exposure_to_word_of_god" {
		t.Fatalf("performing well: %+v", well)
	}
	if len(summary.groups[2]) != 1 || summary.groups[2][0].label != "Leadership" {
		t.Fatalf("warning: %+v", summary.groups[2])
	}
	if empty := summarize(nil); empty.average != nil || empty.tone != "neutral" || len(empty.groups) != 3 {
		t.Fatalf("no scores: %+v", empty)
	}
}

func TestCountsAreWrittenWithThousands(t *testing.T) {
	for n, want := range map[int]string{0: "0", 394: "394", 1000: "1,000", 16152: "16,152", 1234567: "1,234,567"} {
		if got := thousands(n); got != want {
			t.Errorf("%d: %s", n, got)
		}
	}
}

func TestAPageOutOfRangeIsTheLast(t *testing.T) {
	cases := []struct {
		requested   int32
		total       int
		page, pages int
	}{
		{0, 700, 1, 14}, {2, 700, 2, 14}, {999, 700, 14, 14}, {-3, 700, 14, 14}, {0, 0, 1, 1}, {5, 0, 1, 1}, {1, 50, 1, 1}, {2, 51, 2, 2},
	}
	for _, c := range cases {
		if page, pages := pick(c.requested, c.total); page != c.page || pages != c.pages {
			t.Errorf("pick(%d, %d) = %d of %d, want %d of %d", c.requested, c.total, page, pages, c.page, c.pages)
		}
	}
}

func TestTheYearTurnsInOctober(t *testing.T) {
	if fy := operationalFY(time.Date(2026, 9, 30, 23, 0, 0, 0, time.UTC)); fy != 2026 {
		t.Errorf("30 September: %d", fy)
	}
	if fy := operationalFY(time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)); fy != 2027 {
		t.Errorf("1 October: %d", fy)
	}
	if got := fyOptions(time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)); len(got) != 4 || got[0] != "2025" || got[3] != "2028" {
		t.Errorf("options: %v", got)
	}
}

func TestOwnersAreRankedByLeadThenOfficer(t *testing.T) {
	directory := map[string]owner{
		"a": {name: "Zed", plName: "Lead B"}, "b": {name: "Amy", plName: "Lead B"},
		"c": {name: "Bob", plName: "Lead A"}, "d": {name: "Cal", plName: ""},
	}
	got := ownerRanking([]string{"x", "d", "a", "b", "c"}, directory)
	want := []string{"c", "b", "a", "d", "x"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("ranking %v, want %v", got, want)
		}
	}
}

func TestSearchEscapesLikeDjango(t *testing.T) {
	if got := likeContains(`50%_off\`); got != `%50\%\_off\\%` {
		t.Fatalf("pattern %q", got)
	}
}

func TestRowActionsFollowTheRole(t *testing.T) {
	keys := func(p auth.Principal, clustered, projects, takeable bool) []string {
		out := []string{}
		for _, a := range actions(p, clustered, projects, takeable) {
			out = append(out, a.GetKey())
		}
		return out
	}
	role := func(r string) auth.Principal { return auth.Principal{Account: auth.Account{ActiveRole: r}} }
	if got := keys(role("ImpactAssessment"), true, true, false); len(got) != 4 || got[0] != "schedule" ||
		got[1] != "change_cluster" || got[2] != "reassign_owner" || got[3] != "assign_to_project" {
		t.Errorf("IA: %v", got)
	}
	if got := keys(role("CCEO"), false, true, true); len(got) != 4 || got[0] != "take" || got[1] != "complete" || got[2] != "add_to_cluster" {
		t.Errorf("CCEO on an unheld school: %v", got)
	}
	disabled := actions(role("CCEO"), false, false, false)
	if last := disabled[len(disabled)-1]; last.GetEnabled() || last.GetReason() != "No active project available." {
		t.Errorf("no project: %+v", last)
	}
	if got := keys(role("RegionalProgramLead"), true, true, false); len(got) != 0 {
		t.Errorf("RPL: %v", got)
	}
}

func TestOnlyTheRolesTheExistingGateLetsInOpenTheDirectory(t *testing.T) {
	for role, want := range map[string]bool{
		"CCEO": true, "Program Lead": true, "ImpactAssessment": true, "CountryDirector": true, "Admin": true,
		"ProjectCoordinator": true, "RegionalProgramLead": true, "PartnerAdmin": false, "Accountant": false,
		"RegionalVicePresident": false, "ClusterLeader": false,
	} {
		if got := rules.PageAccess[role].Directory; got != want {
			t.Errorf("%s: %v, want %v", role, got, want)
		}
	}
}
