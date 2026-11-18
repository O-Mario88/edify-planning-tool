package closurepages

import (
	"net/url"
	"testing"
	"time"
)

func TestABlockersNextStepFollowsItsReason(t *testing.T) {
	cases := map[string]string{
		"Evidence missing":       "CCEO must upload field visit stamp or attendance sheet.",
		"IA checklist":           "IA auditor must verify the checklist details.",
		"NetSuite ID missing":    "Accountant must enter NetSuite Expense ID.",
		"Advance not accounted":  "Reconcile outstanding disbursements.",
		"Evidence and IA review": "CCEO must upload field visit stamp or attendance sheet.",
	}
	for reason, want := range cases {
		if got := nextAction(reason); got != want {
			t.Errorf("%q: got %q, want %q", reason, got, want)
		}
	}
}

func TestABlockerOnWorkNobodyHoldsReadsUnassigned(t *testing.T) {
	now := time.Date(2026, 11, 18, 12, 0, 0, 0, time.UTC)
	blocks := blockedBlocks([]blocker{{activityID: "abcdefghij", kind: "school_visit", reason: "x", role: "CCEO",
		created: now.Add(-3 * time.Hour)}}, url.Values{}, now)
	cells := blocks[0].GetTable().GetRows()[0].GetCells()
	if cells[3].GetText() != "Unassigned" || cells[0].GetText() != "#abcdefgh School Visit" {
		t.Errorf("cells %q, %q", cells[0].GetText(), cells[3].GetText())
	}
}
