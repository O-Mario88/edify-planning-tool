package schoolprofile

import (
	"testing"
	"time"
)

func TestFiguresArePrintedAsDjangoPrintsThem(t *testing.T) {
	// Each answer is Django's own (django.template.defaultfilters.floatformat).
	for _, c := range []struct {
		x    float64
		n    int
		want string
	}{
		{3.45, 1, "3.5"}, {6.25, 1, "6.3"}, {0.05, 1, "0.1"}, {9.95, 1, "10.0"}, {2.0, 1, "2.0"},
		{6.849999, 1, "6.8"}, {0.3476001, 6, "0.347600"}, {32.58250049, 6, "32.582500"}, {-0.04, 1, "0.0"}, {10, 1, "10.0"},
	} {
		if got := floatformat(c.x, c.n); got != c.want {
			t.Errorf("floatformat(%v, %d) = %q, want %q", c.x, c.n, got, c.want)
		}
	}
	// A float added at run time (Go adds constants exactly).
	tenth, fifth := 0.1, 0.2
	for x, want := range map[float64]string{6.0: "6.0", 4.8: "4.8", 6.25: "6.25", tenth + fifth: "0.30000000000000004"} {
		if got := pyFloat(x); got != want {
			t.Errorf("str(%v) = %q, want %q", x, got, want)
		}
	}
}

func TestDatesAreKampalasDays(t *testing.T) {
	day := time.Date(2026, 9, 5, 0, 0, 0, 0, time.UTC)
	if jMY(day) != "5 Sep 2026" || dMY(day) != "05 Sep 2026" {
		t.Fatalf("%q %q", jMY(day), dMY(day))
	}
	// 22:30 UTC on the 8th is already the 9th in Kampala.
	if got := localJMY(time.Date(2026, 11, 8, 22, 30, 0, 0, time.UTC)); got != "9 Nov 2026" {
		t.Fatalf("moment: %q", got)
	}
	if fy := localFY(time.Date(2026, 9, 30, 21, 30, 0, 0, time.UTC)); fy != "2027" {
		t.Fatalf("1 October in Kampala is the new year: %s", fy)
	}
}

func TestActionKeysAreThePageBlocksSlugs(t *testing.T) {
	for text, want := range map[string]string{
		"Edit Details": "edit_details", "Enter SSA Score": "enter_ssa_score", "Assign to Partner": "assign_to_partner",
		"  Re-assign  Owner! ": "re_assign_owner",
	} {
		if got := slug(text); got != want {
			t.Errorf("slug(%q) = %q, want %q", text, got, want)
		}
	}
}

func TestACoreLifecycleSchoolHasACoreTab(t *testing.T) {
	keys := func(schoolType string) []string {
		out := []string{}
		for _, tab := range tabs(school{Type: schoolType}, "details") {
			out = append(out, tab.GetKey())
		}
		return out
	}
	if got := keys("client"); len(got) != 7 || got[6] != "details" {
		t.Errorf("client: %v", got)
	}
	for _, schoolType := range []string{"core", "core_trained", "core_graduate", "champion"} {
		if got := keys(schoolType); len(got) != 8 || got[6] != "core" {
			t.Errorf("%s: %v", schoolType, got)
		}
	}
	if open := tabs(school{Type: "client"}, "details"); !open[6].GetActive() || open[0].GetActive() {
		t.Error("the Details tab is the open one")
	}
}

func TestTheYearsSSABadgeSaysWhereItCameFrom(t *testing.T) {
	score := 6.0
	confirmed := ssaRecord{average: &score, status: "confirmed", source: "staff_keyed", onVisit: true}
	badge := confirmed.badge("2027")
	if badge.GetText() != "SSA FY2027: 6.0" || badge.GetTone() != "good" || badge.GetTitle() != "Source: Keyed on a visit · Confirmed" {
		t.Fatalf("confirmed: %+v", badge)
	}
	zero := 0.0
	pending := ssaRecord{average: &zero, status: "pending"}
	badge = pending.badge("2027")
	if badge.GetText() != "SSA FY2027: — · Pending" || badge.GetTone() != "plain" || badge.GetTitle() != "Source: Recorded · Pending" {
		t.Fatalf("pending: %+v", badge)
	}
	if (ssaRecord{source: "file_import"}).sourceLabel() != "File import" || (ssaRecord{source: "staff_keyed"}).sourceLabel() != "Keyed by staff" {
		t.Fatal("source labels")
	}
}

func TestDataQualityIsTonedByItsStatus(t *testing.T) {
	score := 70
	for status, want := range map[string]string{"Clean": "good", "Needs Review": "plain", "Needs Cleanup": "caution", "Missing Critical Data": "alert"} {
		s := status
		panel := quality(school{QualityScore: &score, QualityStatus: &s})
		if got := panel.GetBadges()[0].GetTone(); got != want {
			t.Errorf("%s: %s, want %s", status, got, want)
		}
		if meter := panel.GetItems()[0].GetMeter(); meter.GetValue() != "70%" || meter.GetFraction() != 0.7 {
			t.Errorf("meter: %+v", meter)
		}
	}
}

func TestOnlyTheRolesTheExistingGatesAdmitOpenProfiles(t *testing.T) {
	for role, want := range map[string]bool{
		"CCEO": true, "Program Lead": true, "Admin": true, "ImpactAssessment": true, "CountryDirector": true,
		"ProjectCoordinator": true, "BusinessTransformationOfficer": true, "PartnerAdmin": false, "ClusterLeader": false,
	} {
		if got := rules.Doors[role].Profile; got != want {
			t.Errorf("%s: %v, want %v", role, got, want)
		}
	}
	if !rules.Doors["Admin"].DeleteSchool || rules.Doors["CCEO"].DeleteSchool {
		t.Error("deletion is the Admin's alone")
	}
}

func TestTheLineUnderAFigureIsCutAsThePageCutsIt(t *testing.T) {
	// Each pair is what the existing Overview drew (helper, then note).
	for helper, want := range map[string]string{
		"0 to 0":                             "0 to 0",
		"of 1 in FY 2026/27":                 "of 1 in FY 2026/27",
		"0 in school · 0 at group trainings": "0 in school",
		"1 approved · 2 with a reviewer":     "1 approved",
		"0 schools · 0 for EdTech":           "0 schools · 0 for EdTech",
		"learners on the school record":      "",
		"previous 5.90":                      "",
		"FY 2026/27":                         "",
	} {
		if got := briefHelper(helper); got != want {
			t.Errorf("briefHelper(%q) = %q, want %q", helper, got, want)
		}
	}
	block := strip("Learners",
		kpi{label: "Enrolment", value: "105", helper: "learners on the school record"},
		kpi{label: "Growth", value: "+9.4%", helper: "96 to 105"},
		kpi{label: "enrolment", value: "1"},
	).GetStrip()
	if len(block.GetMetrics()) != 2 {
		t.Fatalf("a label is drawn once: %v", block.GetMetrics())
	}
	if m := block.GetMetrics()[0]; m.GetHelper() != "" || m.GetNote() != "learners on the school record" {
		t.Errorf("a sentence goes to the note: %+v", m)
	}
	if m := block.GetMetrics()[1]; m.GetHelper() != "96 to 105" || m.GetNote() != "" {
		t.Errorf("a short figure stays: %+v", m)
	}
}

func TestPeriodsAreTheYearsQuartersAndMonths(t *testing.T) {
	for period, want := range map[string][3]string{
		"Q1": {"2025-10-01", "2026-01-01", "Q1 (Oct–Dec)"},
		"Q2": {"2026-01-01", "2026-04-01", "Q2 (Jan–Mar)"},
		"Q4": {"2026-07-01", "2026-10-01", "Q4 (Jul–Sep)"},
		"M1": {"2025-10-01", "2025-11-01", "Oct 2025"},
		"M4": {"2026-01-01", "2026-02-01", "Jan 2026"},
	} {
		w := periodWindow("2026", period)
		if w.start.Format("2006-01-02") != want[0] || w.end.Format("2006-01-02") != want[1] || w.label != want[2] {
			t.Errorf("%s: %v %v %q", period, w.start, w.end, w.label)
		}
	}
	if !periodWindow("2026", "").whole() || !periodWindow("2026", "M13").whole() || knownPeriod("M13") {
		t.Error("the whole year, and a period that is not one")
	}
	if fyLabel("2027") != "FY 2026/27" || previousFY("2027") != "2026" {
		t.Error("year labels")
	}
}

func TestWordsAreWrittenAsTheRecordsWriteThem(t *testing.T) {
	if status("in_review") != "In review" || status("LEARNING_OUTCOMES") != "Learning outcomes" || status("") != "" {
		t.Error("status")
	}
	if projectStatus("on_hold") != "On Hold" || intcomma(1234567) != "1,234,567" || intcomma(-1200) != "-1,200" {
		t.Error("project status or thousands")
	}
	people := []person{{"u1", "Amy"}, {"u2", "Bob"}, {"u3", "Cal"}, {"u4", "Dee"}}
	if f := peopleFact("CCEO", people, true, "/staff/"); f.GetLabel() != "CCEOs" || f.GetValue() != "Amy, Bob, Cal and 1 more" || f.GetHref() != "/staff/u1" {
		t.Errorf("many: %+v", f)
	}
	if f := peopleFact("CCEO", nil, true, "/staff/"); f.GetLabel() != "CCEOs" || f.GetValue() != "Not assigned" {
		t.Errorf("none: %+v", f)
	}
	if f := peopleFact("Programme Lead", people[:1], false, "/staff/"); f.GetLabel() != "Programme Lead" || f.GetHref() != "" {
		t.Errorf("one, not linked: %+v", f)
	}
}

func TestAChangeIsJudgedByThePublishedRuleElseAnyMove(t *testing.T) {
	up, down := 6.1, 5.7
	if c := (ruleBook{}).overallChange(&down, &up); c.status != "improved" || *c.delta != 0.4 || c.tone() != "success" {
		t.Errorf("any rise counts without a rule: %+v", c)
	}
	half := 0.5
	book := ruleBook{{"leadership", ""}: {threshold: &half, direction: "improve"}}
	if c := book.interventionChange("leadership", &down, &up); c.status != "no_change" {
		t.Errorf("under the threshold: %+v", c)
	}
	if c := book.overallChange(nil, &up); c.status != "not_comparable" || c.delta != nil || c.label() != "No comparison yet" {
		t.Errorf("one year missing: %+v", c)
	}
}
