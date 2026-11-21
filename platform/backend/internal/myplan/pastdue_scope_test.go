package myplan

import "testing"

// The past-due figure says what it holds, beside the dashboard's Overdue
// Tasks (past_due_scope_line, apps/my_plan/test_past_due_service.py).
func TestPastDueScopeLine(t *testing.T) {
	for _, c := range []struct {
		p    PastDue
		want string
	}{
		{PastDue{}, ""},
		{PastDue{notStarted: 1, underWay: 1, unfinishedDone: 1},
			"Any age: 1 not started, 1 started or returned, 1 done but missing a Salesforce ID or form"},
		{PastDue{unfinishedDone: 8}, "Any age: 8 done but missing a Salesforce ID or form"},
		{PastDue{notStarted: 2, unfinishedDone: 3}, "Any age: 2 not started, 3 done but missing a Salesforce ID or form"},
	} {
		if got := c.p.ScopeLine(); got != c.want {
			t.Errorf("ScopeLine() = %q, want %q", got, c.want)
		}
	}
}

func TestPastDueStageSplitsLiveWork(t *testing.T) {
	var p PastDue
	p.stage(&activity{status: "scheduled"})
	p.stage(&activity{status: "in_progress"})
	p.stage(&activity{status: "returned_by_pl"})
	if p.notStarted != 1 || p.underWay != 2 {
		t.Fatalf("stage: not started %d, under way %d; want 1 and 2", p.notStarted, p.underWay)
	}
}
