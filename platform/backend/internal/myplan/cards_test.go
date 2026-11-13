package myplan

import (
	"testing"
	"time"
)

func TestComputeNextActionTakesTheFirstBranchThatApplies(t *testing.T) {
	today := time.Date(2026, 11, 13, 0, 0, 0, 0, time.UTC)
	later := today.AddDate(0, 0, 3)
	cases := []struct {
		name   string
		a      activity
		x      extra
		advs   []advance
		action string
		text   string
	}{
		{"waiting for the owner", activity{status: "awaiting_owner_approval"}, extra{}, nil, "await_owner", "Waiting for owner approval"},
		{"sent back", activity{status: "returned_by_pl"}, extra{}, nil, "fix", "Fix and Resubmit"},
		{"due today", activity{status: "rescheduled", plannedDate: &today}, extra{}, nil, "start", "Start"},
		{"scheduled later", activity{status: "scheduled", plannedDate: &later}, extra{}, nil, "view", "View Details"},
		{"in progress", activity{status: "in_progress"}, extra{}, nil, "complete", "Complete Activity"},
		{"begun, nothing in", activity{status: "completion_started"}, extra{evidence: sp("none")}, nil, "complete", "Complete Activity"},
		{"no Salesforce ID", activity{status: "completed"}, extra{evidence: sp("none")}, nil, "sf_id", "Enter Activity SF ID"},
		{"an SSA to upload", activity{status: "completed", activityType: "school_visit_ssa_collection", hasSchool: true}, extra{evidence: sp("accepted"), schoolSSAStatus: sp("not_done")}, nil, "ssa", "Upload SSA"},
		{"the SSA in", activity{status: "completed", activityType: "school_visit_ssa_collection", hasSchool: true}, extra{evidence: sp("accepted"), schoolSSAStatus: sp("done")}, nil, "view", "View Details"},
		{"with IA", activity{status: "awaiting_ia_verification", iaVerification: sp("pending")}, extra{}, nil, "view_status", "View Status"},
		{"verified, accounts pending", activity{status: "ia_verified", iaVerification: sp("confirmed")}, extra{payment: sp("none")}, nil, "view_status", "View Accounts Status"},
		{"money back owed", activity{status: "closed"}, extra{}, []advance{{status: "disbursed"}, {status: "reimbursement_disbursed"}}, "reimbursement_receipt", "Confirm Reimbursement Receipt"},
		{"receipt confirmed", activity{status: "closed"}, extra{}, []advance{{status: "reimbursement_disbursed", receiptConfirmed: true}}, "view", "View Details"},
		{"accountability owed", activity{status: "closed"}, extra{}, []advance{{status: "disbursed"}}, "accountability", "Submit Accountability"},
		{"accountability in", activity{status: "closed"}, extra{}, []advance{{status: "disbursed", accountabilityDone: true}}, "view", "View Details"},
		{"with the Accountant", activity{status: "closed"}, extra{}, []advance{{status: "accountability_pending"}}, "view_status", "Awaiting Finance Clearance"},
		{"with the Lead", activity{status: "closed"}, extra{}, []advance{{status: "reimbursement_pl_pending"}}, "view_status", "Awaiting PL Claim Approval"},
	}
	for _, c := range cases {
		c.a.id = "a1"
		got, ok := computeNextAction(&c.a, &c.x, c.advs, today)
		if !ok || got.action != c.action || got.text != c.text {
			t.Errorf("%s: %+v (%v), want %s %q", c.name, got, ok, c.action, c.text)
		}
	}
	// Two of the last loop's states: which comes first is the table's order.
	if _, ok := computeNextAction(&activity{status: "closed"}, &extra{}, []advance{{status: "reimbursement_submitted"}, {status: "accountability_pl_pending"}}, today); ok {
		t.Error("two of the last loop's states should pass the page on")
	}
}

func TestTheWaitingCardTakesWhatTheEarlierSectionsLeave(t *testing.T) {
	today := time.Date(2026, 11, 13, 0, 0, 0, 0, time.UTC)
	soon := today.AddDate(0, 0, 7)
	view := nextAction{action: "view_status"}
	cases := []struct {
		name string
		a    activity
		x    extra
		next nextAction
		advs []advance
		want bool
	}{
		{"handed in", activity{status: "submitted_to_pl"}, extra{}, nextAction{action: "view"}, nil, true},
		{"with IA, not yet approved", activity{status: "awaiting_ia_verification"}, extra{}, view, nil, true},
		{"approved, no money", activity{status: "ia_verified"}, extra{payment: sp("none")}, view, nil, false},
		{"approved, paid", activity{status: "ia_verified"}, extra{payment: sp("paid")}, view, nil, true},
		{"approved, a claim with the Lead", activity{status: "closed"}, extra{payment: sp("none")}, view, []advance{{status: "reimbursement_pl_pending"}}, true},
		{"waiting on the reader", activity{status: "submitted_to_pl"}, extra{}, nextAction{action: "sf_id"}, nil, false},
		{"this week", activity{status: "in_progress", plannedDate: &soon}, extra{}, view, nil, false},
		{"sent back", activity{status: "returned"}, extra{}, view, nil, false},
	}
	for _, c := range cases {
		if got := onWaitingCard(&c.a, &c.x, c.next, c.advs, today); got != c.want {
			t.Errorf("%s: %v, want %v", c.name, got, c.want)
		}
	}
}

func TestTheBadgeStripIsOnePillOrItsWords(t *testing.T) {
	r := &planRow{row: &row{a: &activity{status: "submitted_to_pl"}, statusLabel: "Submitted", budgetStatus: "Approved"}, tone: "blue"}
	if c := r.badgeStrip(); c.GetBadge() || c.GetText() != "Submitted Approved — Ready for Disbursement" {
		t.Errorf("strip %v", c)
	}
	r.statusLabel = ""
	if c := r.badgeStrip(); !c.GetBadge() || c.GetTone() != "green" {
		t.Errorf("one pill %v", c)
	}
	r.x.reviewNote = sp("  two   spaces ")
	if got := r.returnReason(); got != "two spaces" {
		t.Errorf("reason %q", got)
	}
	r.x.reviewNote = sp("   ")
	if got := r.returnReason(); got != "Correction required" {
		t.Errorf("reason %q", got)
	}
}
