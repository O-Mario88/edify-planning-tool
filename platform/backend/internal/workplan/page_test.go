package workplan

import (
	"testing"
	"time"
)

func day(y, m, d int) time.Time { return time.Date(y, time.Month(m), d, 0, 0, 0, 0, time.UTC) }

func ptr[T any](v T) *T { return &v }

func getter(q map[string]string) func(string) string {
	return func(k string) string { return q[k] }
}

func TestTheYearAndPeriodAreReadAsTheViewReadsThem(t *testing.T) {
	today := day(2026, 11, 13)
	cases := []struct {
		name          string
		query         map[string]string
		next          string
		fy, view, per string
	}{
		{"opens on the running year's month", nil, "", "2027", "month", "11"},
		{"opens on the planning year once it is open", nil, "2028", "2028", "month", "10"},
		{"a planning year the selector does not offer is not opened on", nil, "2031", "2027", "month", "11"},
		{"a year not offered is the default", map[string]string{"fy": " 2026 "}, "", "2027", "month", "11"},
		{"another year opens on October", map[string]string{"fy": "2026"}, "", "2026", "month", "10"},
		{"a month as Python's int reads it", map[string]string{"period": " 1_2 "}, "", "2027", "month", "12"},
		{"a month out of range", map[string]string{"period": "13"}, "", "2027", "month", "11"},
		{"a month not a number", map[string]string{"period": "May"}, "", "2027", "month", "11"},
		{"the year changed with the form resets the month", map[string]string{"fy": "2026", "fy_prev": "2027", "period": "3"}, "", "2026", "month", "10"},
		{"the same year keeps it", map[string]string{"fy": "2026", "fy_prev": "2026", "period": "3"}, "", "2026", "month", "3"},
		{"a quarter in the running year", map[string]string{"view": "quarter"}, "", "2027", "quarter", "Q1"},
		{"a quarter is case-sensitive", map[string]string{"view": "quarter", "period": "q2"}, "", "2027", "quarter", "Q1"},
		{"another year's quarter opens on Q1", map[string]string{"view": "quarter", "fy": "2028", "period": "Q9"}, "", "2028", "quarter", "Q1"},
		{"the year has no period", map[string]string{"view": "fy", "period": "3"}, "", "2027", "fy", ""},
		{"an unknown view is the month", map[string]string{"view": " fy "}, "", "2027", "month", "11"},
	}
	for _, c := range cases {
		s := readState(getter(c.query), "CCEO", c.next, today)
		if s.fy != c.fy || s.view != c.view || s.period() != c.per {
			t.Errorf("%s: got %s %s %q, want %s %s %q", c.name, s.fy, s.view, s.period(), c.fy, c.view, c.per)
		}
	}
}

func TestOnlyAProgramLeadHasTwoAudiences(t *testing.T) {
	today := day(2026, 11, 13)
	if s := readState(getter(nil), "Program Lead", "", today); s.scope != "team" {
		t.Errorf("a Program Lead opens on the team, got %s", s.scope)
	}
	if s := readState(getter(map[string]string{"scope": "own"}), "Program Lead", "", today); s.scope != "own" {
		t.Errorf("own is asked for, got %s", s.scope)
	}
	if s := readState(getter(map[string]string{"scope": "team"}), "CCEO", "", today); s.scope != "own" || s.base()[9].value != "" {
		t.Errorf("an officer has their own plan and no scope in links, got %s", s.scope)
	}
}

func TestLinksEditTheQueryAsTheViewDoes(t *testing.T) {
	base := []kv{{"fy", "2027"}, {"view", "month"}, {"period", "11"}, {"status", ""}, {"flag", ""}, {"scope", "team"}}
	cases := []struct {
		got, want string
	}{
		{link(base), "/work-plan?fy=2027&view=month&period=11&scope=team"},
		{link(base, kv{"flag", "at_risk"}), "/work-plan?fy=2027&view=month&period=11&scope=team&flag=at_risk"},
		{link(base, kv{"view", "fy"}, kv{"period", ""}, kv{"flag", ""}), "/work-plan?fy=2027&view=fy&scope=team"},
		{link(base, kv{"scope", "own"}, kv{"responsible", ""}), "/work-plan?fy=2027&view=month&period=11&scope=own"},
		{link([]kv{{"status", ""}}), "/work-plan"},
		{link([]kv{{"responsible", "a b&c"}}), "/work-plan?responsible=a+b%26c"},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("got %s, want %s", c.got, c.want)
		}
	}
}

func TestUnitCostIsTheAverageToTheCentHalfUp(t *testing.T) {
	cases := []struct {
		cost  int64
		count int
		want  string
	}{
		{62000, 1, "62,000"}, {62000, 2, "31,000"}, {100, 3, "33.33"}, {200, 3, "66.67"},
		{1, 8, "0.13"}, {5, 200, "0.03"}, {0, 4, "0"}, {1500000, 7, "214,285.71"}, {1234567891, 1, "1,234,567,891"},
	}
	for _, c := range cases {
		if got := unitCost(c.cost, c.count); got != c.want {
			t.Errorf("%d / %d: got %s, want %s", c.cost, c.count, got, c.want)
		}
	}
}

func TestDatesReadAsTheTableWritesThem(t *testing.T) {
	cases := []struct {
		start, end *time.Time
		want       string
	}{
		{nil, nil, "Not dated"},
		{ptr(day(2026, 8, 14)), nil, "14 August 2026"},
		{ptr(day(2026, 8, 14)), ptr(day(2026, 8, 14)), "14 August 2026"},
		{ptr(day(2026, 8, 12)), ptr(day(2026, 8, 14)), "12–14 August 2026"},
		{ptr(day(2026, 8, 28)), ptr(day(2026, 9, 2)), "28 August – 2 September 2026"},
		{ptr(day(2026, 12, 30)), ptr(day(2027, 1, 2)), "30 December 2026 – 2 January 2027"},
	}
	for _, c := range cases {
		if got := dateLabel(c.start, c.end); got != c.want {
			t.Errorf("got %q, want %q", got, c.want)
		}
	}
}

func TestTitleCaseIsPythons(t *testing.T) {
	for in, want := range map[string]string{
		"in person": "In Person", "online live": "Online Live", "1st visit": "1St Visit", "": "", "ÉCOLE mixte": "École Mixte",
	} {
		if got := titleCase(in); got != want {
			t.Errorf("%q: got %q, want %q", in, got, want)
		}
	}
}

func TestTheNextActionFollowsComputeNextActionsOrder(t *testing.T) {
	today := day(2026, 11, 13)
	cases := []struct {
		name     string
		a        activity
		advances []advance
		want     string
	}{
		{"waiting for the owner", activity{status: "awaiting_owner_approval"}, nil, "Waiting for owner approval"},
		{"returned partner work", activity{status: "returned_by_ia", delivery: "partner"}, nil, "Correct Returned Evidence"},
		{"returned staff work", activity{status: "returned"}, nil, "Fix and Resubmit"},
		{"partner evidence in", activity{status: "partner_scheduled", delivery: "partner", evidence: "uploaded"}, nil, "Submit Evidence to IA"},
		{"due today", activity{status: "rescheduled", planned: ptr(today)}, nil, "Start"},
		{"a partner booking ahead", activity{status: "partner_scheduled", delivery: "partner", evidence: "none", planned: ptr(today.AddDate(0, 0, 3))}, nil, "Prepare"},
		{"under way", activity{status: "in_progress"}, nil, "Complete Activity"},
		{"partner work begun without its form", activity{status: "completion_started", delivery: "partner", evidence: "none"}, nil, "Upload Evidence"},
		{"staff work begun", activity{status: "completion_started", evidence: "none"}, nil, "Complete Activity"},
		{"completed without an ID", activity{status: "completed", evidence: "none"}, nil, "Enter Activity SF ID"},
		{"a meeting with nobody recorded", activity{status: "completed", evidence: "none", salesforce: ptr("SV-1"), activityType: "cluster_meeting"}, nil, "View Details"},
		{"ready to submit", activity{status: "completed", evidence: "none", salesforce: ptr("SV-1"), activityType: "cluster_meeting", teachersAttended: ptr(1)}, nil, "Submit"},
		{"an SSA still to come", activity{status: "scheduled", activityType: "baseline_ssa_visit", schoolPK: ptr("s"), schoolSSA: ptr("pending")}, nil, "Upload SSA"},
		{"waiting for verification", activity{status: "awaiting_ia_verification", iaVerification: "pending"}, nil, "View Status"},
		{"accounts pending", activity{status: "ia_verified", iaVerification: "confirmed", payment: "none"}, nil, "View Accounts Status"},
		{"a reimbursement sent", activity{status: "ia_verified"}, []advance{{status: "disbursed"}, {status: "reimbursement_disbursed"}}, "Confirm Reimbursement Receipt"},
		{"money out without accountability", activity{status: "ia_verified"}, []advance{{status: "disbursed", netsuite: ptr("")}}, "Submit Accountability"},
		{"accountability with the accountant", activity{status: "ia_verified"}, []advance{{status: "disbursed", netsuite: ptr("NS")}, {status: "accountability_pending"}}, "Awaiting Finance Clearance"},
		{"a claim with the lead", activity{status: "ia_verified"}, []advance{{status: "reimbursement_pl_pending"}}, "Awaiting PL Claim Approval"},
		{"nothing to do", activity{status: "scheduled"}, nil, "View Details"},
	}
	for _, c := range cases {
		c.a.id = "a1"
		if got := nextAction(&c.a, today, c.advances); got.text != c.want {
			t.Errorf("%s: got %q, want %q", c.name, got.text, c.want)
		}
	}
}

func TestARowsOwnActionIsWorkPlanAction(t *testing.T) {
	open := &activity{id: "a1", status: "scheduled", planned: ptr(day(2026, 11, 20))}
	if got := tableAction(open, true, true, "", "", ""); got == nil || got.text != "Reschedule" || !got.own || !got.complete {
		t.Errorf("own dated work: %+v", got)
	}
	undated := &activity{id: "a1", status: "planned"}
	if got := tableAction(undated, true, true, "", "", ""); got == nil || got.text != "Schedule" || got.complete {
		t.Errorf("own undated work: %+v", got)
	}
	partner := &activity{id: "a1", status: "scheduled", delivery: "partner", planned: ptr(day(2026, 11, 20))}
	if got := tableAction(partner, true, true, "", "", ""); got != nil {
		t.Errorf("own partner work has no table action: %+v", got)
	}
	if got := tableAction(open, false, true, "u1", "Paul", "PL"); got == nil || got.text != "Send to PL" ||
		got.url != "/messages/new?context_type=activity&context_id=a1&to=u1" ||
		got.description != "Review an activity-linked message to Paul before sending" {
		t.Errorf("the Director's message: %+v", got)
	}
	if got := tableAction(open, false, false, "u1", "Paul", ""); got != nil {
		t.Errorf("a reader who never acts: %+v", got)
	}
	done := &activity{id: "a1", status: "deferred"}
	if got := tableAction(done, true, true, "", "", ""); got == nil || got.text != "View" {
		t.Errorf("closed work is viewed: %+v", got)
	}
}

func TestEveryRowLinkHasAnExportedAnswer(t *testing.T) {
	door := rules.Doors["CCEO"]
	for _, link := range []string{
		"/my-plan/a1", "/my-plan/a1/reschedule-drawer", "/my-plan/a1/confirm-reimbursement-receipt",
		"/my-plan/a1/accountability", "/activities/a1/complete", "/activities/a1/start",
		"/activities/a1/evidence", "/activities/a1/salesforce-id", "/activities/a1/submit",
		"/partner/activities/a1/evidence", "/planning/visit-requests", "/messages/new?context_type=activity",
	} {
		opens(door, link)
	}
	if opens(door, "/partner/activities/a1/evidence") {
		t.Error("an officer may not open a partner's evidence page")
	}
}

func TestPanelLinesPairAsTheFeedPairsThem(t *testing.T) {
	items := paired([]string{"November 2026", "1 activity", "UGX 62,000", "0 completed", "1 at risk"})
	if len(items) != 4 || items[0].GetText() != "November 2026" || items[1].GetRows().GetRows()[0].GetValue() != "UGX 62,000" ||
		items[2].GetText() != "0 completed" {
		t.Errorf("a band: %v", items)
	}
	items = paired([]string{"Grand total", "1,204 activities", "UGX 0"})
	if len(items) != 2 || items[1].GetRows().GetRows()[0].GetLabel() != "1,204 activities" {
		t.Errorf("the grand total: %v", items)
	}
}

func TestARecordedEidIsKnownHoweverSpelt(t *testing.T) {
	for title, want := range map[string]string{
		"Idd el-Fitri": rules.DayOff.EidAlFitr, "EID UL-ADHA": rules.DayOff.EidAlAdha, "Idd Adhuha": rules.DayOff.EidAlAdha,
		"Christmas": "",
	} {
		if got := eidNamed(title); got != want {
			t.Errorf("%q: got %q, want %q", title, got, want)
		}
	}
	if (dayOffMark{holiday: true}).label() != "Public holiday" || (dayOffMark{leave: true}).label() != "On leave" ||
		(dayOffMark{holiday: true, leave: true}).label() != "Holiday and leave" {
		t.Error("day-off labels")
	}
}

func TestEveryWorkingWeekOfTheCalendarIsWrittenOut(t *testing.T) {
	r := rules.DayOff
	if r.HolidayYears[0] > 2025 || r.HolidayYears[1] < 2035 {
		t.Errorf("the national calendar covers %v", r.HolidayYears)
	}
	days := map[string]bool{}
	for _, h := range r.Holidays {
		days[h.Date] = true
	}
	for _, d := range []string{"2026-12-25", "2026-10-09", "2027-03-26"} { // Christmas, Independence, Good Friday
		if !days[d] {
			t.Errorf("%s is not a holiday", d)
		}
	}
}

func TestMoneyIsWrittenWithCommas(t *testing.T) {
	for n, want := range map[int64]string{0: "0", 999: "999", 1000: "1,000", 1234567: "1,234,567", -62000: "-62,000"} {
		if got := comma(n); got != want {
			t.Errorf("%d: got %s, want %s", n, got, want)
		}
	}
}
