package clusteroversight

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"net/url"
	"slices"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func f(v float64) *float64 { return &v }

func principal(role string) auth.Principal {
	p := auth.Principal{}
	p.ActiveRole = role
	return p
}

// Neither a path that is not the page's nor a refused role reads anything,
// so the service needs no database here.
func TestOnlyThePageItselfIsAnsweredAndOnlyForItsRoles(t *testing.T) {
	s := NewService(nil, nil)
	for _, path := range []string{"/cluster-oversight", "/cluster-oversight/ssa", "/cluster-oversight/scoring", "/cluster-oversight/command/"} {
		_, served, err := s.Build(context.Background(), principal("Admin"), path, url.Values{})
		if !served || !errors.Is(err, ErrNotAvailable) {
			t.Errorf("%s: served %v, %v; the feed does not open it", path, served, err)
		}
	}
	for _, path := range []string{"/clusters", "/cluster-oversights/", "/cluster-management/"} {
		if _, served, err := s.Build(context.Background(), principal("Admin"), path, url.Values{}); served || err != nil {
			t.Errorf("%s: served %v, %v; it is not this page's", path, served, err)
		}
	}
	for _, role := range []string{"ProjectCoordinator", "BusinessTransformationOfficer", "Partner", "NoSuchRole", ""} {
		_, served, err := s.Build(context.Background(), principal(role), Path, url.Values{})
		if !served || !errors.Is(err, ErrNotAvailable) {
			t.Errorf("%q: served %v, %v; the page refuses the role", role, served, err)
		}
	}
	for _, role := range []string{"CCEO", "Program Lead", "ImpactAssessment", "CountryDirector", "RegionalVicePresident", "RegionalProgramLead", "Accountant", "Admin"} {
		if !rules.Doors[role].Page {
			t.Errorf("%s may open the page", role)
		}
	}
}

func TestAMoveIsJudgedByItsRule(t *testing.T) {
	c := rules.Change
	maintain := changeRule{direction: c.MaintainDirection}
	cases := []struct {
		name          string
		before, after float64
		rule          changeRule
		want          string
		delta         float64
	}{
		{"any rise with no threshold", 5, 5.01, fallbackRule, c.Improved, 0.01},
		{"any fall with no threshold", 5, 4.99, fallbackRule, c.Declined, -0.01},
		{"a move that rounds to nothing", 5, 5.004, fallbackRule, c.NoChange, 0},
		{"a rise that reaches the threshold", 5, 5.5, changeRule{threshold: f(0.5)}, c.Improved, 0.5},
		{"a rise short of it", 5, 5.49, changeRule{threshold: f(0.5)}, c.NoChange, 0.49},
		{"a fall that reaches it", 5, 4.5, changeRule{threshold: f(0.5)}, c.Declined, -0.5},
		{"a fall short of it", 5, 4.51, changeRule{threshold: f(0.5)}, c.NoChange, -0.49},
		{"a strong score held", 9, 8, maintain, c.MaintainedStrong, -1},
		{"a strong score lost", 9, 7.99, maintain, c.Declined, -1.01},
		{"a weak score that rose is still not strong", 3, 7, maintain, c.Declined, 4},
	}
	for _, tc := range cases {
		got, delta := changeBetween(tc.before, tc.after, tc.rule)
		if got != tc.want || delta != tc.delta {
			t.Errorf("%s: %s (%v), want %s (%v)", tc.name, got, delta, tc.want, tc.delta)
		}
	}
}

func TestARuleIsTheCountrysThenTheDeploymentsThenTheFallback(t *testing.T) {
	book := newRuleBook([]changeRuleRow{
		{Intervention: "leadership", Country: "", Direction: "improve", Threshold: f(0.5)},
		{Intervention: "leadership", Country: "", Direction: "improve", Threshold: f(9)}, // older: not read
		{Intervention: "leadership", Country: " Kenya ", Threshold: f(-0.25)},
		{Intervention: "", Threshold: f(5)},
	})
	threshold := func(r changeRule) float64 {
		if r.threshold == nil {
			return math.NaN()
		}
		return *r.threshold
	}
	if got := book.rule("leadership", " Kenya"); threshold(got) != 0.25 || got.direction != "improve" {
		t.Errorf("Kenya's rule: %v %s", threshold(got), got.direction)
	}
	if got := book.rule("leadership", "Uganda"); threshold(got) != 0.5 {
		t.Errorf("the deployment's rule for a country with none: %v", threshold(got))
	}
	if got := book.rule("enrolment", "Kenya"); got.threshold != nil || got.direction != "improve" {
		t.Errorf("the fallback: %v", got)
	}
	// A school's mean is judged by the mean of its areas' thresholds, one
	// with none counting as nothing.
	if got := book.schoolRule([]string{"leadership", "enrolment", ""}, "Uganda"); threshold(got) != 0.25 {
		t.Errorf("the school's rule: %v", threshold(got))
	}
	if got := book.schoolRule([]string{"enrolment"}, ""); got.threshold != nil {
		t.Errorf("no approved threshold among the school's areas: %v", *got.threshold)
	}
}

func TestReadingsLessThanTheIntervalApartAreNotCompared(t *testing.T) {
	for _, tc := range []struct {
		start, end string
		want       bool
	}{
		{"2026-03-01", "2026-06-28", false}, // 119 days
		{"2026-03-01", "2026-06-29", true},  // 120 days
		{"2026-06-29", "2026-03-01", false},
		{"", "2026-06-29", true},
	} {
		if got := comparable(tc.start, tc.end); got != tc.want {
			t.Errorf("%s to %s: %v", tc.start, tc.end, got)
		}
	}
}

func TestTheLeastPerformingInterventionIsTheLowestMeanThenTheFirstByKey(t *testing.T) {
	scored := map[string]schoolScore{
		"a": {overall: f(6), areas: []scoreRow{{Intervention: "leadership", Score: 4}, {Intervention: "enrolment", Score: 4}, {Intervention: "financial_health", Score: 9}}},
		"b": {areas: []scoreRow{{Intervention: "leadership", Score: 5}, {Intervention: "enrolment", Score: 5}}},
	}
	got := ssaNowOf([]string{"a", "b", "not scored"}, scored)
	if got.weakest != "enrolment" || got.weakestMean != 4.5 || *got.average != 6 {
		t.Fatalf("%+v", got)
	}
	if none := ssaNowOf([]string{"not scored"}, scored); none.weakest != "" || none.average != nil {
		t.Fatalf("a cluster with no assessed school: %+v", none)
	}
}

func TestASchoolsYearIsItsNewestRecordAndALaterScoreReplacesAnEarlier(t *testing.T) {
	got := currentScores(
		[]yearRecordRow{{ID: "new", SchoolID: "a"}, {ID: "old", SchoolID: "a", Average: f(1)}, {ID: "b1", SchoolID: "b", Average: f(7.126)}},
		[]scoreRow{
			{RecordID: "new", Intervention: "leadership", Score: 4.006}, {RecordID: "new", Intervention: "enrolment", Score: 6},
			{RecordID: "new", Intervention: "leadership", Score: 5}, {RecordID: "old", Intervention: "enrolment", Score: 1},
		})
	a := got["a"]
	if len(a.areas) != 2 || a.areas[0] != (scoreRow{"new", "leadership", 5}) || *a.overall != 5.5 {
		t.Errorf("a: %+v overall %v", a.areas, a.overall)
	}
	if b := got["b"]; *b.overall != 7.13 || len(b.areas) != 0 {
		t.Errorf("b: %+v", b)
	}
}

func TestTrainedReadingsCountTheTwoYearsTrainingsWithANamedArea(t *testing.T) {
	c := rules.Change
	attended := map[string]bool{"a": true, "b": true, "guest": true}
	facts := facts{
		attendance: attendance{allSessions: []session{
			{fy: "2027", area: "leadership", isTraining: true, attended: attended},
			{fy: "2026", area: "leadership", isTraining: true, attended: attended},
			{fy: "2025", area: "leadership", isTraining: true, attended: attended}, // before the two years
			{fy: "2027", area: "leadership", attended: attended},                   // a meeting
			{fy: "2027", area: "", isTraining: true, attended: attended},           // no named area
			{fy: "2027", area: "not_an_area", isTraining: true, attended: attended},
			{fy: "2027", area: overall, isTraining: true, attended: attended},
		}},
		movement: map[string]*areaMovement{
			"leadership": {verdicts: map[string]string{"a": c.Improved, "b": c.Declined}},
			overall:      {verdicts: map[string]string{"a": c.MaintainedStrong}},
		},
	}
	if better, pairs := facts.trainedPairs("2027"); better != 3 || pairs != 5 {
		t.Fatalf("%d of %d readings rose, want 3 of 5", better, pairs)
	}
}

func TestAScoreNeedsEnoughMeasuredPartsAndScalesTheRestAway(t *testing.T) {
	parts := func(scores ...*float64) []part {
		out := []part{}
		for i, s := range scores {
			out = append(out, part{weight: float64(10 * (i + 1)), score: s})
		}
		return out
	}
	cases := []struct {
		name string
		c    composite
		want *int
	}{
		{"three of three", composite{parts: parts(f(100), f(50), f(0)), minDimensions: 3}, intp(33)},
		{"two measured of three needed", composite{parts: parts(f(100), nil, f(0)), minDimensions: 3}, nil},
		{"a part left out, its weight scaled away", composite{parts: parts(f(100), nil, f(50)), minDimensions: 2}, intp(62)},
		{"a score of fewer parts than it needs asks for all it has", composite{parts: parts(f(40), f(60)), minDimensions: 5}, intp(53)},
		{"a part weighted nothing is not counted", composite{parts: []part{{weight: 0, score: f(100)}, {weight: 5, score: f(20)}}, minDimensions: 1}, intp(20)},
		{"no weight at all", composite{parts: []part{{weight: 0, score: f(100)}}, minDimensions: 0}, nil},
		{"a half rounds to the even number", composite{parts: []part{{weight: 1, score: f(62.5)}}, minDimensions: 1}, intp(62)},
	}
	for _, tc := range cases {
		got := tc.c.score()
		if (got == nil) != (tc.want == nil) || (got != nil && *got != *tc.want) {
			t.Errorf("%s: %v, want %v", tc.name, show(got), show(tc.want))
		}
	}
}

func intp(v int) *int { return &v }

func show(v *int) any {
	if v == nil {
		return "no score"
	}
	return *v
}

func TestABandIsHighMediumLowOrNotEnoughData(t *testing.T) {
	for _, tc := range []struct {
		score       *int
		label, tone string
	}{
		{intp(100), "High", "success"}, {intp(70), "High", "success"}, {intp(69), "Medium", "warning"},
		{intp(40), "Medium", "warning"}, {intp(39), "Low", "danger"}, {intp(0), "Low", "danger"},
		{nil, "Not enough data", "neutral"},
	} {
		if label, tone := band(tc.score); label != tc.label || tone != tc.tone {
			t.Errorf("%v: %s %s", show(tc.score), label, tone)
		}
	}
}

func TestAStoredWeightIsANumberNeverBelowZeroElseTheDefault(t *testing.T) {
	raw := func(v string) json.RawMessage { return json.RawMessage(v) }
	for _, tc := range []struct {
		stored string
		want   float64
		ok     bool
	}{
		{`12`, 12, true}, {`12.5`, 12.5, true}, {`"7"`, 7, true}, {`" 7.5 "`, 7.5, true}, {`"1e2"`, 100, true},
		{`true`, 1, true}, {`false`, 0, true}, {`-3`, -3, true},
		{`null`, 0, false}, {`"many"`, 0, false}, {`""`, 0, false}, {`[1]`, 0, false}, {`{"a":1}`, 0, false}, {`"0x10"`, 0, false},
	} {
		if got, ok := pyFloat(raw(tc.stored)); ok != tc.ok || got != tc.want {
			t.Errorf("%s: %v %v", tc.stored, got, ok)
		}
	}
	if got, ok := pyFloat(nil); ok || got != 0 {
		t.Errorf("a part the row does not name: %v %v", got, ok)
	}
	if notNegative(-3) != 0 || notNegative(math.NaN()) != 0 || notNegative(2.5) != 2.5 {
		t.Error("a weight is never below zero, and one that is not a number is zero")
	}
	s := settingsOf(&settingRow{
		Health:   map[string]json.RawMessage{"meetings": raw(`-5`), "trainings": raw(`"35"`), "unknown": raw(`9`), "planning": raw(`null`)},
		Maturity: map[string]json.RawMessage{"min_dimensions": raw(`2.9`), "other": raw(`1`)},
	})
	if h := s.weights["health"]; h["meetings"] != 0 || h["trainings"] != 35 || h["planning"] != 10 || len(h) != 6 {
		t.Errorf("health weights: %v", h)
	}
	if s.maturity["min_dimensions"] != 2.9 || s.maturity["model_stories"] != 2 || len(s.maturity) != len(rules.MaturityDefaults) {
		t.Errorf("maturity rules: %v", s.maturity)
	}
	if d := settingsOf(nil); d.weights["impact"]["ssa"] != 25 || d.maturity["min_dimensions"] != 3 {
		t.Errorf("the defaults: %v", d)
	}
}

func TestTheTablesPageIsANumberFromOneUpClampedToThePagesThereAre(t *testing.T) {
	for _, tc := range []struct {
		asked         string
		total         int
		number, pages int
	}{
		{"", 120, 1, 3}, {"2", 120, 2, 3}, {" 3 ", 120, 3, 3}, {"99", 120, 3, 3}, {"0", 120, 1, 3}, {"-4", 120, 1, 3},
		{"abc", 120, 1, 3}, {"2.0", 120, 1, 3}, {"+2", 120, 2, 3}, {"2", 50, 1, 1}, {"1", 0, 1, 1}, {"2", 51, 2, 2},
	} {
		if number, pages := pageNumber(tc.asked, tc.total); number != tc.number || pages != tc.pages {
			t.Errorf("%q of %d rows: page %d of %d, want %d of %d", tc.asked, tc.total, number, pages, tc.number, tc.pages)
		}
	}
}

func TestThePagerShowsTheEndsAndOnePageEitherSide(t *testing.T) {
	for _, tc := range []struct {
		current, pages int
		want           []int
	}{
		{1, 1, []int{1}}, {4, 7, []int{1, 2, 3, 4, 5, 6, 7}},
		{1, 8, []int{1, 2, 0, 8}}, {2, 8, []int{1, 2, 3, 0, 8}}, {3, 8, []int{1, 2, 3, 4, 0, 8}},
		{4, 8, []int{1, 0, 3, 4, 5, 0, 8}}, {6, 8, []int{1, 0, 5, 6, 7, 8}}, {7, 8, []int{1, 0, 6, 7, 8}},
		{8, 8, []int{1, 0, 7, 8}},
	} {
		if got := window(tc.current, tc.pages); !slices.Equal(got, tc.want) {
			t.Errorf("page %d of %d: %v, want %v", tc.current, tc.pages, got, tc.want)
		}
	}
}

func TestAPageLinkKeepsTheQueryButNotItsOwnPageOrADownload(t *testing.T) {
	query := url.Values{"rows_page": {"3"}, "fy": {"2026"}, "area": {"a b&c"}, "format": {"csv"}, "export": {"1"}, "empty": {""}}
	if got := carried(query); got != "area=a+b%26c&fy=2026&" {
		t.Fatalf("%q", got)
	}
	if got := carried(url.Values{"rows_page": {"3"}}); got != "" {
		t.Fatalf("%q", got)
	}
}

func TestFiguresReadAsTheExistingPageWritesThem(t *testing.T) {
	negativeZero := math.Copysign(0, -1)
	for got, want := range map[string]string{
		signed(1.25, 1, ""):                   "+1.2",
		signed(-0.04, 1, ""):                  "-0.0",
		signed(negativeZero, 1, "%"):          "-0.0%",
		signed(0, 1, ""):                      "0.0",
		floatStr(5):                           "5.0",
		floatStr(6.4):                         "6.4",
		commas(1234567):                       "1,234,567",
		commas(999):                           "999",
		fixed(4.25, 1):                        "4.2",
		interventionLabel("leadership"):       "Leadership",
		interventionLabel("new_area_2028x9y"): "New Area 2028X9Y",
		plural(1, "cluster"):                  "1 cluster",
		plural(0, "cluster"):                  "0 clusters",
		collapse("  Cluster \n  002 "):        "Cluster 002",
	} {
		if got != want {
			t.Errorf("%q, want %q", got, want)
		}
	}
	if toneOf(nil) != "" || toneOf(f(negativeZero)) != "neutral" || toneOf(f(0.1)) != "success" || toneOf(f(-0.1)) != "danger" {
		t.Error("a figure's tone: none where it is not there, neutral for no movement, green up, red down")
	}
	if pyRound(2.675, 2) != 2.67 || pyRound(0.125, 2) != 0.12 || pyRoundInt(0.5) != 0 || pyRoundInt(1.5) != 2 || pyRoundInt(2.5) != 2 {
		t.Error("rounding is from the exact value, ties to even")
	}
}
