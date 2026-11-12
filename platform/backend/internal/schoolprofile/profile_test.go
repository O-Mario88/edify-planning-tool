package schoolprofile

import (
	"context"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
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

func TestTheBestAndTheStrugglingInterventionArePickedAsTheEngineDoes(t *testing.T) {
	v := func(f float64) *float64 { return &f }
	row := func(key string, previous, current *float64) ivRow {
		r := ivRow{key: key, label: key, previous: previous, current: current}
		r.verdict = (ruleBook{}).interventionChange(key, previous, current)
		return r
	}
	if best, struggling := picks([]ivRow{row("a", nil, nil)}); best != nil || struggling != nil {
		t.Fatal("nothing measured, nothing picked")
	}
	// Rises win by the change; the struggling one declined most.
	best, struggling := picks([]ivRow{
		row("a", v(5), v(6)), row("b", v(4), v(6)), row("c", v(7), v(6.5)), row("d", v(8), v(5)),
	})
	if best.row.key != "b" || best.basis != "change" || struggling.row.key != "d" || struggling.basis != "change" {
		t.Fatalf("by change: %s %s, %s %s", best.row.key, best.basis, struggling.row.key, struggling.basis)
	}
	// No rise and no fall: by this year's score, the first of equals kept.
	best, struggling = picks([]ivRow{row("a", nil, v(6)), row("b", nil, v(7)), row("c", nil, v(7)), row("d", nil, v(5))})
	if best.row.key != "b" || best.basis != "score" || struggling.row.key != "d" || struggling.basis != "score" {
		t.Fatalf("by score: %s %s, %s %s", best.row.key, best.basis, struggling.row.key, struggling.basis)
	}
	// One measured: it is not its own opposite.
	if best, struggling = picks([]ivRow{row("a", nil, v(6)), row("b", nil, nil)}); best == nil || struggling != nil {
		t.Fatal("one measured")
	}
}

func TestAPairIsJudgedByTheCountrysRuleFirst(t *testing.T) {
	half, one := 0.5, 1.0
	book := ruleBook{
		{"leadership", ""}:       {threshold: &half, direction: "improve"},
		{"leadership", "Uganda"}: {threshold: &one, direction: "improve"},
		{"enrolment", ""}:        {direction: "maintain_strong"},
	}
	if r := book.ruleIn("leadership", "Uganda"); *r.threshold != 1 {
		t.Errorf("the country's rule: %v", *r.threshold)
	}
	if r := book.ruleIn("leadership", "Kenya"); *r.threshold != 0.5 {
		t.Errorf("the deployment's rule: %v", *r.threshold)
	}
	if r := book.ruleIn("financial_health", "Uganda"); r.threshold != nil || r.direction != "improve" {
		t.Errorf("any move: %+v", r)
	}
	// The school's rule is the mean of the thresholds, a missing one as 0.
	r, words := book.schoolRuleIn([]string{"leadership", "financial_health"}, "Uganda")
	if *r.threshold != 0.5 || words != "±0.5 (mean of the approved domain rules)" {
		t.Errorf("mean rule: %v %q", *r.threshold, words)
	}
	if _, words := book.schoolRuleIn([]string{"financial_health"}, ""); words != "Any change (no approved threshold)" {
		t.Errorf("fallback: %q", words)
	}
	// Holding a strong score is its own verdict.
	if c := between(8.5, 8.2, book.ruleIn("enrolment", "")); c.status != "maintained_strong" {
		t.Errorf("maintained strong: %+v", c)
	}
}

func TestTextIsWrittenAsTheTemplateFiltersWriteIt(t *testing.T) {
	// str.title() and Django's |title, as Python answers.
	for in, want := range map[string]string{"in school training": "In School Training", "ssa's 2nd visit": "Ssa's 2nd Visit", "": ""} {
		if got := djangoTitle(in); got != want {
			t.Errorf("title(%q) = %q, want %q", in, got, want)
		}
	}
	if got := pyTitle("ssa's 2nd visit"); got != "Ssa'S 2Nd Visit" {
		t.Errorf("str.title: %q", got)
	}
	// |truncatechars:60 keeps 59 characters and an ellipsis.
	long := "Reading corners for P1 to P3, with the head teacher\nand two class teachers"
	if got := truncateChars(long, 60); got != long[:59]+"…" {
		t.Errorf("truncatechars: %q", got)
	}
	if got := truncateChars("short", 60); got != "short" {
		t.Errorf("truncatechars short: %q", got)
	}
	// Python's round() takes a half to the even neighbour.
	if pyRoundInt(12.5) != 12 || pyRoundInt(13.5) != 14 || attendanceRate(1, 3) != 33 || attendanceRate(0, 0) != 0 {
		t.Error("rounding")
	}
}

func TestALabelAndItsFigureAreReadAsOneRow(t *testing.T) {
	items := pairedItems([]*screensv1.PagePanelItem{
		heading("Room to Read — Partner Activity"), text("Scheduled for 7 Apr 2026"),
		text("Next: Pay the partner — Accountant"), text("UGX 40,000"), text("Completed"),
		text("Finding"), text("Showing 1"),
	})
	if len(items) != 6 || items[2].GetRows().GetRows()[0].GetValue() != "UGX 40,000" || items[3].GetText() != "Completed" {
		t.Fatalf("paired: %v", items)
	}
}

func TestEachActivityReadsItsStatusAsTheListDoes(t *testing.T) {
	today := time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC)
	past, now, later := today.AddDate(0, 0, -1), today, today.AddDate(0, 0, 3)
	for _, c := range []struct {
		a           listedActivity
		label, tone string
	}{
		{listedActivity{status: "ia_verified"}, "Complete", "success"},
		{listedActivity{status: "awaiting_ia_verification", delivery: "partner"}, "IA Pending", "info"},
		{listedActivity{status: "awaiting_ia_verification"}, "PL Pending", "info"},
		{listedActivity{status: "evidence_uploaded", salesforceID: "SV-1"}, "Evidence Uploaded", "warning"},
		{listedActivity{status: "evidence_uploaded"}, "Activity ID Missing", "warning"},
		{listedActivity{status: "returned_by_pl", planned: &past}, "Returned for Correction", "danger"},
		{listedActivity{status: "scheduled", planned: &past}, "Overdue", "danger"},
		{listedActivity{status: "scheduled", planned: &now}, "Due Today", "warning"},
		{listedActivity{status: "rescheduled", reschedules: 1, planned: &later}, "Rescheduled", "info"},
		{listedActivity{status: "partner_scheduled", planned: &later}, "Partner Scheduled", "info"},
		{listedActivity{status: "scheduled"}, "Scheduled", "info"},
	} {
		if label, tone := activityStatus(c.a, today); label != c.label || tone != c.tone {
			t.Errorf("%s: %s/%s, want %s/%s", c.a.status, label, tone, c.label, c.tone)
		}
	}
}

func TestALeadReadsTheTeamsWorkAndRunsTheirOwn(t *testing.T) {
	lead := reader{p: auth.Principal{UserID: "u-lead", StaffProfileID: "s-lead", ActiveRole: "Program Lead"},
		scope: schooldirectory.Scope{Role: "Program Lead", UserID: "u-lead", StaffID: "s-lead",
			SchoolIDs: []string{"own", "team"}, OwnSchoolIDs: []string{"own"}, SupervisedStaffIDs: []string{"s-officer"},
			OwnDistrictIDs: []string{"d1"}}, ownersRead: true, clusterOwners: []string{"u-lead", "s-lead"}}
	ctx := context.Background()
	for _, c := range []struct {
		a    listedActivity
		want bool
	}{
		{listedActivity{schoolID: "team", staffID: "s-officer"}, false},
		{listedActivity{schoolID: "own", staffID: "s-officer"}, true},
		{listedActivity{schoolID: "team", staffID: "u-lead"}, true},
		{listedActivity{schoolID: "team", monitorID: "s-lead"}, true},
		{listedActivity{clusterID: "c", clusterLive: true, clusterLead: "s-officer"}, false},
		{listedActivity{clusterID: "c", clusterLive: true, clusterDistrict: "d1"}, true},
	} {
		if got, err := lead.mayExecute(ctx, c.a); err != nil || got != c.want {
			t.Errorf("%+v: %v, want %v", c.a, got, c.want)
		}
	}
	// A Country Director reads the team's work and runs only their own.
	cd := reader{p: auth.Principal{UserID: "u-cd"}, scope: schooldirectory.Scope{Role: "CountryDirector", CountryScope: true}}
	if got, _ := cd.mayExecute(ctx, listedActivity{staffID: "s-officer"}); got {
		t.Error("the director runs an officer's work")
	}
	if !cd.maySchedule(listedActivity{}) || !cd.inScope(listedActivity{}) {
		t.Error("the director cannot reach the work")
	}
}

func TestTheCoreTabWordsItsFiguresAsThePageDoes(t *testing.T) {
	c := corePerformance{hasPlan: true, visitsDone: 3, visitsTarget: 4, trainingsDone: 5, trainingsTarget: 4, invited: 8, attended: 1}
	// Each kind capped at its target: (3 + 4) of 8.
	if got := c.packageLabel(); got != "88%" {
		t.Errorf("package: %q", got)
	}
	if r := c.attendanceRate(); r == nil || *r != 12 {
		t.Errorf("12.5%% rounds to the even neighbour: %v", r)
	}
	if signedFloat(0.1) != "+0.1" || signedFloat(-0.2) != "-0.2" || signedFloat(0) != "0.0" {
		t.Error("signed figures")
	}
	ten := 10
	var leaders *int
	addHeadcount(&leaders, nil)
	if leaders != nil {
		t.Error("a missing headcount stays missing")
	}
	n := int32(3)
	addHeadcount(&leaders, &n)
	if dashInt(leaders) != "3" || dashInt(nil) != "—" || dashInt(&ten) != "10" {
		t.Error("headcounts")
	}
}

func TestChampionReadinessListsTheOfficialChecks(t *testing.T) {
	sc := school{ID: "s1", SchoolID: "1006"}
	potential := corePerformance{champion: rules.CoreTab.Champion.Potential,
		metrics: &championMetrics{latestAvg: 8.25, lowestScore: 7.0, lowestIntervention: "leadership", totalSlots: 8, completedSlots: 8, eligible: true}}
	panel := potential.championPanel(doors{CoreSchools: true}, sc).GetPanel()
	lines := panel.GetItems()[0].GetLinks().GetLinks()
	if panel.GetTitle() != "Champion Readiness: Potential Champion" ||
		lines[0].GetText() != "Met: Latest SSA average 8.0 or more (now 8.3)" ||
		lines[1].GetText() != "Met: No intervention below 7.0 (lowest 7.0, leadership)" ||
		lines[2].GetText() != "Met: All package visits and trainings done (8 of 8)" {
		t.Fatalf("the checks: %v", lines)
	}
	last := panel.GetItems()[len(panel.GetItems())-1].GetLinks().GetLinks()[0]
	if last.GetText() != "Open Champion review" || last.GetHref() != "/core-schools/1006/champion-review" || !last.GetDrawer() {
		t.Fatalf("the review: %v", last)
	}
	// Without the rule's inputs, each check is not judged and says why.
	unjudged := corePerformance{champion: rules.CoreTab.Champion.Insufficient}.championPanel(doors{}, sc).GetPanel()
	if got := unjudged.GetItems()[0].GetLinks().GetLinks()[0].GetText(); got != "Not judged: Latest SSA average 8.0 or more" {
		t.Errorf("unjudged: %q", got)
	}
	if unjudged.GetItems()[1].GetText() != "The rule needs a confirmed SSA and a Core plan to judge this school." {
		t.Error("the reason")
	}
}

func TestRecommendationsOfferPlanSupportToWhoeverMayAct(t *testing.T) {
	score := 6.1
	recs := []coreRecommendation{{intervention: "financial_health", score: &score, band: "Improving", reason: "Weak twice.", state: "accepted"},
		{intervention: "leadership", state: "planned"}}
	blocks := recommendationBlocks(recs, true, school{ID: "s1"})
	items := blocks[1].GetPanel().GetItems()
	if blocks[0].GetSection() != "Recommended Support" || items[0].GetText() != "Financial Health (6.1, Improving)" ||
		items[2].GetText() != "Accepted for planning" || items[3].GetLinks().GetLinks()[0].GetHref() != "/planning/schedule-modal?school_id=s1" {
		t.Fatalf("an owner's: %v", items)
	}
	if read := recommendationBlocks(recs, false, school{ID: "s1"})[1].GetPanel().GetItems(); len(read) != 5 {
		t.Fatalf("a reader's has no Plan support: %v", read)
	}
	if none := recommendationBlocks(nil, true, school{}); none[0].GetPanel().GetTitle() != "Recommended Support" {
		t.Fatalf("none: %v", none)
	}
}
