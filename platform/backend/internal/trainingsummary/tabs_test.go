package trainingsummary

import (
	"net/url"
	"testing"
	"time"
)

func TestASummaryRowFlagsWhereItStandsAgainstItsCeiling(t *testing.T) {
	for _, c := range []struct {
		name                      string
		row                       summaryRow
		flag, tone, ceiling, left string
		excess                    string
		total, awaiting           int
	}{
		{"unset", summaryRow{group: 1, inSchool: 1, partner: 2, partnerScheduled: 1, both: 1}, "No ceiling set", "neutral", "Not set", "View", "0", 3, 1},
		{"above", summaryRow{ceiling: ptr(1), group: 2}, "1 above ceiling", "danger", "1", "0", "1", 2, 0},
		{"below", summaryRow{ceiling: ptr(1200), inSchool: 3}, "1,197 below ceiling", "warning", "1,200", "1,197", "0", 3, 0},
		{"reached", summaryRow{ceiling: ptr(2), partner: 2, partnerScheduled: 2}, "At ceiling", "success", "2", "0", "0", 2, 0},
	} {
		cells := byStaffCells(c.row, "2027", true)
		if c.row.total() != c.total || c.row.awaitingPartner() != c.awaiting {
			t.Errorf("%s: total %d awaiting %d", c.name, c.row.total(), c.row.awaitingPartner())
		}
		if got := cells[10]; got.GetText() != c.flag || got.GetTone() != c.tone {
			t.Errorf("%s: status %q %q", c.name, got.GetText(), got.GetTone())
		}
		if cells[2].GetText() != c.ceiling || cells[8].GetText() != c.left || cells[9].GetText() != c.excess {
			t.Errorf("%s: ceiling %q remaining %q excess %q", c.name, cells[2].GetText(), cells[8].GetText(), cells[9].GetText())
		}
		if c.excess != "0" && cells[9].GetTone() != "danger" {
			t.Errorf("%s: excess is drawn red", c.name)
		}
	}
}

func TestByStaffFiguresLinkTheirSchoolsAndZeroIsPlain(t *testing.T) {
	r := summaryRow{staffID: "s1", staffName: "Paul N.", trainingID: "t1", trainingName: "Leadership", partner: 2, partnerScheduled: 1, group: 1}
	cells := byStaffCells(r, "2027", true)
	if cells[0].GetHref() != "/staff/s1" || byStaffCells(r, "2027", false)[0].GetHref() != "" {
		t.Errorf("staff link: %q", cells[0].GetHref())
	}
	if cells[3].GetText() != "0" || cells[3].GetHref() != "" {
		t.Errorf("no staff planned: %+v", cells[3])
	}
	if cells[5].GetTone() != "warning" || cells[5].GetHref() != "/training-summary/schools?staff=s1&training=t1&fy=2027&figure=awaiting" {
		t.Errorf("awaiting: %+v", cells[5])
	}
	if !cells[7].GetStrong() || cells[7].GetText() != "3" {
		t.Errorf("covered: %+v", cells[7])
	}
}

func TestTheByStaffTablePagesAtFiftyAndTheNoteGivesWayToThePager(t *testing.T) {
	rows := make([]summaryRow, 120)
	for i := range rows {
		rows[i] = summaryRow{staffID: "s", trainingID: "t", group: 1}
	}
	table := byStaffTable(rows, "2027", url.Values{"view": {"trainings"}, "tab": {"staff"}, "by_staff_page": {" 9 "}, "fy": {""}}, true).GetTable()
	if len(table.GetRows()) != 20 || table.GetFootnote() != "Showing 101–120 of 120" {
		t.Fatalf("rows %d footnote %q", len(table.GetRows()), table.GetFootnote())
	}
	pages := table.GetPager().GetPages()
	if pages[0].GetLabel() != "Prev" || pages[0].GetHref() != "?tab=staff&view=trainings&by_staff_page=2" || !pages[len(pages)-1].GetCurrent() {
		t.Errorf("pager: %+v", pages)
	}
	if one := byStaffTable(rows[:3], "2027", url.Values{}, true).GetTable(); one.GetPager() != nil || one.GetFootnote() != byStaffNote {
		t.Errorf("one page: %+v", one)
	}
	if empty := byStaffTable(nil, "2027", url.Values{}, true).GetTable(); empty.GetEmptyMessage() != byStaffEmpty ||
		empty.GetSubtitle() != "0 covered · 0 awaiting partner scheduling · FY 2027" || len(empty.GetColumns()) != 0 {
		t.Errorf("empty: %+v", empty)
	}
}

func TestACommitmentReadsItsStatusAndNextAction(t *testing.T) {
	day := time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC)
	for _, c := range []struct {
		route, activity string
		dated           bool
		date            *time.Time
		status, next    string
		scheduled       string
	}{
		{routeStaff, "planned", true, &day, staffPlanned, "Conduct", "5 Nov 2026"},
		{routeStaff, "evidence_uploaded", true, &day, inProgress, "Complete and submit", "5 Nov 2026"},
		{routeGroup, "scheduled", true, nil, groupScheduled, "Conduct", "Yes"},
		{routePartner, "planned", false, nil, partnerAssigned, "Partner to schedule", "No"},
		{routePartner, "planned", true, &day, partnerScheduled, "Partner to conduct", "5 Nov 2026"},
		{routePartner, "in_progress", false, nil, inProgress, "Partner to complete", "Yes"},
		{routePartner, "ia_verified", true, &day, completed, "None", "5 Nov 2026"},
	} {
		r := coverageRow{route: c.route, status: statusOf(c.route, c.activity, c.dated), date: c.date, activityID: "a1"}
		cells := coverageCells(r, true)
		if r.status != c.status || cells[8].GetText() != c.next || cells[7].GetText() != c.scheduled {
			t.Errorf("%s %s: %s %q %q", c.route, c.activity, r.status, cells[8].GetText(), cells[7].GetText())
		}
		if cells[6].GetHref() != "/my-plan/a1" {
			t.Errorf("status link %q", cells[6].GetHref())
		}
	}
	missing := coverageCells(coverageRow{status: notCovered, schoolPK: "k1", schoolName: "A School"}, true)
	if missing[4].GetText() != "—" || missing[5].GetText() != "—" || missing[6].GetTone() != "danger" || missing[6].GetHref() != "" ||
		missing[8].GetText() != "Plan" || missing[7].GetText() != "No" || missing[1].GetHref() != "/schools/k1" {
		t.Errorf("not covered: %+v", missing)
	}
	handover := coverageCells(coverageRow{route: routePartner, status: partnerAssigned, assignmentID: "h1", responsible: "Literacy Uganda"}, true)
	if handover[6].GetHref() != "/partner-oversight/" || handover[5].GetText() != "Literacy Uganda" {
		t.Errorf("hand-over: %+v", handover)
	}
}

func TestASchoolOnTwoSessionsIsListedTwiceAndMarkedOnce(t *testing.T) {
	d1, d2 := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC), time.Date(2026, 10, 2, 0, 0, 0, 0, time.UTC)
	rows := inOrder([]coverageRow{
		{schoolPK: "s1", schoolName: "beta", trainingID: "t", trainingName: "T", staffID: "p", route: routeGroup, cluster: "North", date: &d1, activityID: "a2"},
		{schoolPK: "s1", schoolName: "Beta", trainingID: "t", trainingName: "T", staffID: "p", route: routeGroup, cluster: "North", date: &d2, activityID: "a1"},
		{schoolPK: "s0", schoolName: "Alpha", trainingID: "t", trainingName: "T", staffID: "p", route: routeStaff},
	})
	if rows[0].schoolPK != "s0" || rows[1].activityID != "a1" || !rows[2].repeat || rows[1].repeat {
		t.Fatalf("order: %+v", rows)
	}
	if got := coverageCells(rows[2], true)[4].GetText(); got != "Group Training · North · same school, counted once" {
		t.Errorf("route: %q", got)
	}
}

func TestAwaitingIsTheSchoolsThePartnerHasDatedNoneOf(t *testing.T) {
	rows := []coverageRow{
		{schoolPK: "a", trainingID: "t", staffID: "p", route: routePartner, dated: true},
		{schoolPK: "a", trainingID: "t", staffID: "p", route: routePartner},
		{schoolPK: "b", trainingID: "t", staffID: "p", route: routePartner},
		{schoolPK: "c", trainingID: "t", staffID: "p", route: routeStaff},
	}
	if got := ofFigure(rows, "awaiting"); len(got) != 1 || got[0].schoolPK != "b" {
		t.Errorf("awaiting: %+v", got)
	}
	if got := ofFigure(rows, partnerScheduled); len(got) != 1 {
		t.Errorf("partner scheduled: %+v", got)
	}
	if got := ofFigure(rows, routePartner); len(got) != 3 {
		t.Errorf("partner: %+v", got)
	}
	if got := ofFigure(rows, "covered"); len(got) != 4 {
		t.Errorf("covered: %+v", got)
	}
}

func TestTheCoverageTableSaysWhyItIsEmptyAndCountsSchools(t *testing.T) {
	needs := coverageBlock(coverage{show: showRemaining, needsTraining: true}, "2027", url.Values{}, true).GetTable()
	if needs.GetEmptyMessage() != coverageNeedsTraining || needs.GetSubtitle() != "0 schools · FY 2027" {
		t.Errorf("needs a training: %+v", needs)
	}
	one := coverageBlock(coverage{rows: []coverageRow{{status: staffPlanned}}, schoolCount: 1,
		counts: [][2]string{{"Staff Planned", "1"}}}, "2027", url.Values{}, true).GetTable()
	if one.GetSubtitle() != "1 school · 1 Staff Planned · FY 2027" || one.GetFootnote() != coverageNote || len(one.GetColumns()) != 9 {
		t.Errorf("one school: %+v", one)
	}
}

func TestASelectReadsTheChosenOptionElseItsFirst(t *testing.T) {
	options := [][2]string{{"", "All trainings"}, {"t1", "Leadership"}}
	if f := selectFilter("training", "Training", "t1", options); f.GetValue() != "t1" {
		t.Errorf("chosen: %q", f.GetValue())
	}
	if f := selectFilter("training", "Training", "gone", options); f.GetValue() != "" {
		t.Errorf("unknown: %q", f.GetValue())
	}
	s := summary{staff: []profile{{id: "p1", email: "a@x"}}}
	filters := schoolsFilters(s, nil, "", "p1", "bogus")
	if filters[1].GetValue() != "p1" || filters[1].GetOptions()[1].GetLabel() != "a@x" || filters[2].GetValue() != "" {
		t.Errorf("filters: %+v", filters)
	}
}

func TestThePagerWindowFoldsLongRuns(t *testing.T) {
	got := window(7, 14)
	want := []int{1, 0, 6, 7, 8, 0, 14}
	if len(got) != len(want) {
		t.Fatalf("window = %v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("window = %v, want %v", got, want)
		}
	}
}
