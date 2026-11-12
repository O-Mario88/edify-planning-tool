package myactions

import (
	"net/url"
	"testing"
	"time"
)

func day(s string) *time.Time {
	d, _ := time.Parse("2006-01-02", s)
	return &d
}

func TestTheExportedRolesAreThePagesOwn(t *testing.T) {
	for role, want := range map[string]struct{ page, strip bool }{
		"CCEO": {true, false}, "Admin": {true, false}, "PartnerFieldOfficer": {true, false},
		"ProjectCoordinator": {true, true}, "ClusterLeader": {false, false},
	} {
		got := rules.Roles[role]
		if got.Page != want.page || (got.Strip != nil) != want.strip {
			t.Errorf("%s: %+v, want %+v", role, got, want)
		}
	}
	if rules.RowLimit != 100 || rules.PageSize != 50 {
		t.Errorf("limit %d, page size %d", rules.RowLimit, rules.PageSize)
	}
}

func TestLabelsFallBackAsPythonWritesThem(t *testing.T) {
	for state, want := range map[string]string{"in_progress": "In progress", "returned": "Returned", "weird_state": "Weird_State", "x2y": "X2Y"} {
		if got := stateLabel(state); got != want {
			t.Errorf("stateLabel(%q) = %q, want %q", state, got, want)
		}
	}
	for issue, want := range map[string]string{"no_ssa": "No SSA", "mystery_issue_TYPE": "Mystery issue type", "": ""} {
		if got := issueLabel(issue); got != want {
			t.Errorf("issueLabel(%q) = %q, want %q", issue, got, want)
		}
	}
}

func TestAStateIsAPillUnlessALineSitsUnderIt(t *testing.T) {
	for _, c := range []struct {
		a     action
		text  string
		badge bool
	}{
		{action{State: "open"}, "Open", true},
		{action{State: "open", ReturnedReason: "   "}, "Open", true},
		{action{State: "returned", ReturnedReason: " Not  mine "}, "Returned Not mine", false},
		{action{State: "resolved", ResolvedBySystem: true}, "Resolved Confirmed by the record", false},
		{action{State: "resolved"}, "Resolved Closed manually", false},
	} {
		got := stateCell(c.a)
		if got.GetText() != c.text || got.GetBadge() != c.badge || (got.GetTone() == "primary") != c.badge {
			t.Errorf("%+v: %v, want %q badge %v", c.a, got, c.text, c.badge)
		}
	}
}

func TestLatenessCountsOnlyActiveWorkPastItsDay(t *testing.T) {
	today := *day("2026-11-12")
	for _, c := range []struct {
		a    action
		want string
	}{
		{action{State: "open", DueDate: day("2026-11-11")}, "11 Nov 1 day late"},
		{action{State: "escalated", DueDate: day("2026-11-04")}, "4 Nov 8 days late"},
		{action{State: "open", DueDate: day("2026-11-12")}, "12 Nov"},
		{action{State: "resolved", DueDate: day("2026-11-01")}, "1 Nov"},
		{action{State: "open"}, "—"},
	} {
		if got := due(c.a, today); got != c.want {
			t.Errorf("%+v: %q, want %q", c.a, got, c.want)
		}
	}
}

func TestTheRowOffersOpenOrViewSchool(t *testing.T) {
	if got := actionCell(action{State: "open", Route: "/x"}).GetActions(); len(got) != 1 || got[0].GetKey() != "menu" || got[0].GetPrimary() {
		t.Errorf("active work: %v", got)
	}
	if got := actionCell(action{State: "open"}).GetActions(); len(got) != 0 {
		t.Errorf("a blank route opens nothing: %v", got)
	}
	if got := actionCell(action{State: "cancelled", SchoolPK: "s1"}).GetActions(); len(got) != 1 || got[0].GetHref() != "/schools/s1" || !got[0].GetPrimary() {
		t.Errorf("closed work: %v", got)
	}
	r := row(action{State: "open"}, time.Time{}).GetCells()
	if r[0].GetText() != "—" || r[1].GetText() != "School —" || r[3].GetText() != "—" {
		t.Errorf("a row with no school on file: %v", r)
	}
}

func TestTheQueuePagesAndTheProvenanceLine(t *testing.T) {
	rows := make([]action, 60)
	for i := range rows {
		rows[i] = action{State: "open", SchoolPK: "s"}
	}
	p := page(view{role: rules.Roles["CCEO"], counts: counts{Total: 60, Open: 60, Resolved: 2, AutoResolved: 2}, rows: rows,
		query: url.Values{"tab": {"all"}, pageParam: {"2"}}})
	if got := p.GetBlocks()[0].GetPanel().GetItems()[0].GetText(); got != "2 of 2 resolved actions confirmed by the record." {
		t.Errorf("the provenance line: %q", got)
	}
	if got := len(p.GetBlocks()[2].GetTable().GetRows()); got != 10 {
		t.Errorf("the second page holds %d", got)
	}
	links := p.GetBlocks()[3].GetPanel().GetItems()[1].GetLinks().GetLinks()
	if links[0].GetHref() != "?tab=all&table_rows_page=1" {
		t.Errorf("the pager carries the tab: %v", links)
	}
	empty := page(view{role: rules.Roles["ProjectCoordinator"], query: url.Values{}})
	if empty.GetBlocks()[0].GetLinkTabs() == nil || empty.GetBlocks()[1].GetPanel().GetItems()[1].GetText() != "Nothing has been assigned to you." {
		t.Errorf("the coordinator's empty queue: %v", empty.GetBlocks())
	}
}
