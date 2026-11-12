package activities

import (
	"encoding/json"
	"math"
	"net/url"
	"testing"
	"time"
)

// Each expectation below is the existing code's answer, read from Python
// (numpy 2.5, scipy 1.18) where arithmetic is involved.

func TestNumpySumsPairwiseAsNumpyDoes(t *testing.T) {
	tests := []struct {
		name             string
		values           []float64
		sum, mean, stdev float64
	}{
		{"ten tenths, pairwise (a plain loop gives 0.9999999999999999)", repeat(0.1, 10), 1.0, 0.1, 0},
		{"seven tenths, a plain loop", repeat(0.1, 7), 0.7, 0.09999999999999999, 1.4989724041661926e-17},
		{"seventeen scores", []float64{0.3, 0.1, 0.7, 1.1, 2.2, 0.01, 5.5, 3.3, 0.9, 0.4, 0.15, 7.7, 0.05, 0.6, 1.9, 2.8, 0.33},
			28.04, 1.6494117647058824, 2.146719795956832},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := npSum(tt.values); got != tt.sum {
				t.Fatalf("sum %v, want %v", got, tt.sum)
			}
			peers := make([]map[string]float64, len(tt.values))
			for i, v := range tt.values {
				peers[i] = map[string]float64{"leadership": v}
			}
			stat := peerStats(peers)["leadership"]
			if stat.mean != tt.mean || stat.std != tt.stdev {
				t.Fatalf("mean %v std %v, want %v %v", stat.mean, stat.std, tt.mean, tt.stdev)
			}
		})
	}
}

func repeat(v float64, n int) []float64 {
	out := make([]float64, n)
	for i := range out {
		out[i] = v
	}
	return out
}

func TestTrendIsTheRoundedLeastSquaresSlope(t *testing.T) {
	tests := []struct {
		series  []float64
		urgency float64
	}{
		// Python: 0.5 - 1.6/2.0 is -0.30000000000000004, clipped to 0;
		// 0.5 - (-0.57)/2.0 is 0.7849999999999999.
		{[]float64{4.0, 5.5, 7.2}, 0},
		{[]float64{6.1, 5.0, 5.0, 4.2}, 0.7849999999999999},
		{[]float64{5, 5, 5}, 0.5},
	}
	for _, tt := range tests {
		if got := trendComponent(tt.series); !got.measurable || got.urgency != tt.urgency {
			t.Fatalf("%v: %+v, want urgency %v", tt.series, got, tt.urgency)
		}
	}
	if trendComponent([]float64{3}).measurable {
		t.Fatal("one record has no trend")
	}
}

func TestPriorityCodesFollowTheEngine(t *testing.T) {
	tests := []struct {
		name   string
		ranked []scored
		want   []string
	}{
		{"the top three needs below Strong, then every Critical", []scored{
			{"a", 3}, {"b", 7}, {"c", 6}, {"d", 4.9}, {"e", 9}}, []string{"a", "b", "c", "d"}},
		{"Strong throughout: the weakest", []scored{{"a", 8.5}, {"b", 9}}, []string{"a"}},
		{"nothing ranked", nil, nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := priorityCodes(tt.ranked)
			if len(got) != len(tt.want) {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
			for i := range got {
				if got[i] != tt.want[i] {
					t.Fatalf("got %v, want %v", got, tt.want)
				}
			}
		})
	}
}

func TestPlanNatureAndTheDefaultFocus(t *testing.T) {
	need := schoolNeed{Priorities: []string{"financial_health"}}
	tests := []struct {
		kind, nature, focus string
		collects            bool
	}{
		{"training_follow_up_visit", "support", "financial_health", false},
		{"school_visit_ssa_collection", "collection", "", false},
		{"donor_visit", "not_applicable", "", false},
		{"social_visit", "not_applicable", "", false},
		{"donor_visit", "collection", "", true},
	}
	for _, tt := range tests {
		if got := planNature(tt.kind, []string{"any_ssa_intervention"}, tt.collects); got != tt.nature {
			t.Fatalf("%s: nature %s, want %s", tt.kind, got, tt.nature)
		}
		if got := defaultFocus(tt.kind, []string{"any_ssa_intervention"}, need, tt.collects); got != tt.focus {
			t.Fatalf("%s: focus %q, want %q", tt.kind, got, tt.focus)
		}
	}
	if got := defaultFocus("training_follow_up_visit", []string{"administrative"}, need, false); got != "" {
		t.Fatalf("an administrative item takes no focus, got %q", got)
	}
}

func TestTheVerdictsReasonInTheExistingWords(t *testing.T) {
	day := time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC)
	ssaDate := time.Date(2025, 3, 4, 0, 0, 0, 0, time.UTC)
	pending := time.Date(2026, 2, 1, 6, 0, 0, 0, time.UTC)
	record := &ssaRecord{ID: "ssa1", FY: "2025", Date: &ssaDate}
	need := schoolNeed{Record: record, Priorities: []string{"leadership"}, Ranked: []rankedNeed{
		{Intervention: "leadership", Label: "Leadership", Score: 4.0, Band: "Critical"},
		{Intervention: "enrolment", Label: "Enrolment", Score: 6.5, Band: "Improving"},
	}}
	tests := []struct {
		name, kind, focus string
		need              schoolNeed
		want              string
	}{
		{"collection", "school_visit_ssa_collection", "", need, "Collects the SSA this school's support will be planned from."},
		{"not applicable", "donor_visit", "", need, "Not school-improvement work, so no SSA intervention applies."},
		{"priority", "training_follow_up_visit", "leadership", need, "Targets Leadership (4.0/10, ranked 1 of the school's needs)."},
		{"off priority", "training_follow_up_visit", "enrolment", need,
			"Targets Enrolment (6.5/10, ranked 2 of the school's needs); the SSA ranks Leadership first."},
		{"no focus", "training_follow_up_visit", "", need, "Names no intervention although the SSA ranks Leadership first."},
		{"no SSA, one pending", "training_follow_up_visit", "", schoolNeed{PendingSince: &pending},
			"No verified SSA yet: collect the assessment so support can target a measured need. A newer SSA (2026-02-01) is waiting for verification."},
		{"stale", "training_follow_up_visit", "leadership", schoolNeed{Record: record, Stale: true, Ranked: need.Ranked},
			"The verified SSA (FY2025) is out of date: collect this year's assessment before planning support from it."},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			e := assess(tt.kind, tt.focus, "ssa_default", []string{"any_ssa_intervention"}, tt.need, false, day)
			if got := reasonFor(e); got != tt.want {
				t.Fatalf("got %q\nwant %q", got, tt.want)
			}
		})
	}
}

func TestTheEvidenceIsStoredAsPythonWritesIt(t *testing.T) {
	ssaDate := time.Date(2025, 3, 4, 0, 0, 0, 123000, time.UTC)
	avg := 5.0
	e := assess("donor_visit", "", "", nil, schoolNeed{
		Record: &ssaRecord{ID: "s", FY: "2025", Date: &ssaDate, AverageScore: &avg},
		Ranked: []rankedNeed{{Intervention: "enrolment", Label: "Enrolment", Score: 6.0, Band: "Improving"}},
	}, false, time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC))
	raw, err := json.Marshal(e.Data["school"])
	if err != nil {
		t.Fatal(err)
	}
	want := `{"averageScore":5.0,"focusBand":null,"focusRank":null,"focusScore":null,"priorities":[],` +
		`"ssaDate":"2025-03-04T00:00:00.000123+00:00","ssaFy":"2025","ssaId":"s",` +
		`"top":{"band":"Improving","intervention":"enrolment","label":"Enrolment","score":6.0}}`
	if string(raw) != want {
		t.Fatalf("got  %s\nwant %s", raw, want)
	}
}

func TestPythonFormatting(t *testing.T) {
	if got := pyTitle("financial_health"); got != "Financial_Health" {
		t.Fatalf("title %q", got)
	}
	if got := pyTitle("teacher's environment"); got != "Teacher'S Environment" {
		t.Fatalf("title %q", got)
	}
	reason, _ := standardSupport("", "financial_health", "item", nil)
	if reason != "Standard field support targeting Financial Health." {
		t.Fatalf("reason %q", reason)
	}
	for in, want := range map[float64]string{5: "5.0", 5.4: "5.4", 10: "10.0", 0.30000000000000004: "0.30000000000000004"} {
		if got := pyRepr(in); got != want {
			t.Fatalf("repr(%v) = %q, want %q", in, got, want)
		}
	}
	for in, want := range map[float64]float64{2.675: 2.67, 0.125: 0.12, 1.0049999999999999: 1.005} {
		digits := 2
		if in == 1.0049999999999999 {
			digits = 3
		}
		if got := pyRound(in, digits); got != want {
			t.Fatalf("round(%v) = %v, want %v", in, got, want)
		}
	}
	day := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	if longDate(day) != "1 October 2026" || shortDate(day) != "1 Oct 2026" {
		t.Fatalf("dates %q %q", longDate(day), shortDate(day))
	}
	if thousands(1234567) != "1,234,567" || thousands(560) != "560" {
		t.Fatal("thousands")
	}
	if pyIsoformat(time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)) != "2026-01-02T03:04:05+00:00" {
		t.Fatal("isoformat")
	}
}

func TestTheYearAndQuarterAreReadInUTC(t *testing.T) {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		t.Fatal(err)
	}
	// Midnight on 1 October in Kampala is still 30 September in UTC: the
	// existing get_operational_fy and get_quarter_for_date read UTC.
	day := time.Date(2026, 10, 1, 0, 0, 0, 0, kampala)
	if q := quarterOf(day); q != "Q4" {
		t.Fatalf("quarter %s", q)
	}
	if q := quarterOf(time.Date(2026, 10, 2, 0, 0, 0, 0, kampala)); q != "Q1" {
		t.Fatalf("quarter %s", q)
	}
}

func TestTheDaysDistrictTypeForThePerson(t *testing.T) {
	field := staffHome{Found: true, Roles: []string{"CCEO"}, HomeDistrictID: "home"}
	tests := []struct {
		name string
		h    staffHome
		id   string
		dn   string
		dt   string
		want string
	}{
		{"no district", field, "", "", "", "primary"},
		{"field, at home", field, "home", "Mukono", "secondary", "primary"},
		{"field, away", field, "other", "Mukono", "primary", "secondary"},
		{"field, no home: the district's own", staffHome{Found: true, Roles: []string{"Program Lead"}}, "d", "x", "secondary", "secondary"},
		{"head office in the HQ zone", staffHome{Found: true, Roles: []string{"CountryDirector"}}, "d", " Kampala ", "secondary", "primary"},
		{"head office outside it", staffHome{Found: true, Roles: []string{"CountryDirector"}}, "d", "Gulu", "primary", "secondary"},
		{"no roles: the active role", staffHome{Found: true, ActiveRole: "cceo", HomeDistrictID: "home"}, "home", "x", "secondary", "primary"},
	}
	for _, tt := range tests {
		if got := districtTypeFor(tt.h, tt.id, tt.dn, tt.dt); got != tt.want {
			t.Fatalf("%s: %s, want %s", tt.name, got, tt.want)
		}
	}
}

func TestTheDrawerFormIsTakenOnlyForTheCase(t *testing.T) {
	base := url.Values{
		"school_id": {"1286"}, "purpose_of_visit": {"donor_visit"}, "scheduled_date": {"2026-11-20"},
		"activity_purpose_text": {"why"}, "require_catalogue": {"yes"}, "delivery_type": {"staff"},
		"executor_type": {"staff"}, "activity_type": {"baseline_ssa_visit"}, "catalogue_item_id": {""},
	}
	req, ok := RequestFromForm(base)
	if !ok || req.Goal != "why" || req.SchoolID != "1286" {
		t.Fatalf("taken %v %+v", ok, req)
	}
	for field, value := range map[string]string{
		"assigned_partner_id": "p1", "project_id": "x", "source_activity_id": "a", "cluster_id": "c",
		"focus_intervention": "leadership", "ssa_collection_expected": "yes", "delivery_type": "partner",
		"executor_type": "partner", "require_catalogue": "no",
	} {
		form := url.Values{}
		for k, v := range base {
			form[k] = v
		}
		form.Set(field, value)
		if _, ok := RequestFromForm(form); ok {
			t.Fatalf("%s=%s must be handed on", field, value)
		}
	}
}

func TestTheRulesAreExported(t *testing.T) {
	if len(rules.Doors.Drawer) == 0 || rules.Doors.AdminRefusal == "" || len(rules.order) != len(rules.labels) ||
		len(rules.weights) != 4 || math.Abs(rules.weights[0].value-0.45) > 0 {
		t.Fatalf("rules.json: %+v", rules.Doors)
	}
	for _, p := range inScopePurposes {
		if rules.Purposes.ActivityTypes[p] == "" || !in(rules.Purposes.Staff, p) {
			t.Fatalf("purpose %s is not a staff purpose with a type", p)
		}
	}
}
