package partneroversight

import (
	"testing"
	"time"
)

func day(y int, m time.Month, d int) *time.Time {
	t := time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	return &t
}

func TestAPieceOfPartnerWorkReadsWhereItStands(t *testing.T) {
	today := *day(2026, time.November, 18)
	cases := []struct {
		name                     string
		it                       item
		phase, status, execution string
		ia, payment, withdrawal  string
		overdue                  bool
	}{
		{"waiting on the Partner's date", item{stage: stageAwaiting, assignmentStatus: "assigned"},
			"awaiting_schedule", "Awaiting Schedule", "—", "—", "Not Eligible", "Withdraw assignment", false},
		{"dated by the Partner, ahead", item{stage: stageScheduled, activityID: "a", activityStatus: "partner_scheduled",
			scheduledDate: day(2026, time.November, 28), partnerHasDated: true},
			"scheduled", "Scheduled", "Not Started", "—", "Not Eligible", "Recall scheduled activity", false},
		{"dated by staff, passed", item{stage: stageScheduled, activityID: "a", activityStatus: "scheduled",
			scheduledDate: day(2026, time.November, 13)},
			"scheduled", "Scheduled", "Not Started", "—", "Not Eligible", "Withdraw from partner", true},
		{"in progress", item{stage: stageScheduled, activityID: "a", activityStatus: "in_progress"},
			"in_progress", "In Progress", "In Progress", "—", "Not Eligible", "Suspend delivery and review", false},
		{"evidence uploaded", item{stage: stageScheduled, activityID: "a", activityStatus: "evidence_uploaded", evidenceStatus: "uploaded"},
			"verification", "Verification", "In Progress", "—", "Not Eligible", "Withdraw for quality review", false},
		{"verified, unpaid", item{stage: stageScheduled, activityID: "a", activityStatus: "ia_verified", iaStatus: "confirmed", paymentStatus: "pending"},
			"completed", "Completed", "Evidence Submitted", "Verified", "Awaiting Payment", "Place payment on hold", false},
		{"paid", item{stage: stageScheduled, activityID: "a", activityStatus: "accountant_confirmed", paymentStatus: "paid"},
			"completed", "Completed", "Evidence Submitted", "Verified", "Paid", "", false},
		{"handed back, undecided", item{stage: stageReturned, assignmentStatus: "returned_to_staff"},
			"returned", "Returned to Staff", "—", "—", "Not Eligible", "", false},
	}
	for _, c := range cases {
		it := c.it
		got := []string{it.deliveryPhase(), it.statusLabel(), it.executionStatus(), it.iaStatusLabel(), it.paymentLabel(),
			withdrawalLabelOf(it.withdrawalKind(), it.partnerHasDated)}
		want := []string{c.phase, c.status, c.execution, c.ia, c.payment, c.withdrawal}
		for k := range got {
			if got[k] != want[k] {
				t.Errorf("%s: %q, want %q (all: %q)", c.name, got[k], want[k], got)
				break
			}
		}
		if it.isOverdue(today) != c.overdue {
			t.Errorf("%s: overdue %v, want %v", c.name, it.isOverdue(today), c.overdue)
		}
	}
}

func TestPartnerWorkRisksAndFollowUps(t *testing.T) {
	today := *day(2026, time.November, 18)
	old := &item{stage: stageAwaiting, assignmentDate: day(2026, time.October, 29)}
	if r := risksOf(old, today); len(r) != 1 || r[0] != "partner_schedule_overdue" {
		t.Errorf("a hand-over 20 days old: %v", r)
	}
	cost := int64(0)
	late := &item{stage: stageScheduled, activityID: "a", activityStatus: "scheduled", scheduledDate: day(2026, time.November, 1), plannedCost: &cost}
	if r := risksOf(late, today); len(r) != 2 || r[0] != "partner_delivery_overdue" || r[1] != "partner_rate_missing" {
		t.Errorf("late work with no price: %v", r)
	}
	half := 0.5
	for _, c := range []struct {
		pct     int
		improve *float64
		planned int
		want    string
	}{
		{0, nil, 0, "Insufficient Data"}, {14, &half, 7, "Capacity Review"}, {80, &half, 5, "Assign More Schools"},
		{60, &half, 5, "Keep Active"},
	} {
		if got := recommendation(c.pct, c.improve, c.planned); got != c.want {
			t.Errorf("recommendation(%d, %v, %d) = %q, want %q", c.pct, c.improve, c.planned, got, c.want)
		}
	}
	if percentOrZero(1, 7) != 14 || percentOrZero(1, 8) != 12 || percentOrZero(3, 0) != 0 {
		t.Errorf("percentages: %d %d %d", percentOrZero(1, 7), percentOrZero(1, 8), percentOrZero(3, 0))
	}
	if pyTitle("returned_to staff") != "Returned_To Staff" || pyTitle("school unavailable") != "School Unavailable" {
		t.Errorf("pyTitle: %q %q", pyTitle("returned_to staff"), pyTitle("school unavailable"))
	}
}
