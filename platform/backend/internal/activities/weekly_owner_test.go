package activities

import (
	"errors"
	"testing"
	"time"
)

// weekly_service._submission_status_for: the owner's role routes the request.
func TestASentWeekGoesToWhoeverApprovesItsOwner(t *testing.T) {
	for role, want := range map[string]string{
		"CCEO": "submitted_to_pl", "Program Lead": "submitted_to_cd", "ProjectCoordinator": "submitted_to_cd",
		"ImpactAssessment": "submitted_to_cd", "Accountant": "submitted_to_cd", "HumanResources": "submitted_to_cd",
		"CountryDirector": "confirmed_for_advance", "Admin": "confirmed_for_advance",
	} {
		if got := submissionStatus(role); got != want {
			t.Fatalf("%s = %s, want %s", role, got, want)
		}
	}
}

// weekly_service._owner_role: the role stamped on the request, else the
// owner's active role, else their first role; nobody found is a CCEO.
func TestTheOwnersRoleIsTheOneStampedOnTheRequestFirst(t *testing.T) {
	tests := []struct {
		name, stamped, active string
		found                 bool
		roles                 []string
		want                  string
	}{
		{"stamped", "Program Lead", "CCEO", true, []string{"CCEO"}, "Program Lead"},
		{"active", "", "ProjectCoordinator", true, []string{"CCEO"}, "ProjectCoordinator"},
		{"first role", "", "", true, []string{"ImpactAssessment", "CCEO"}, "ImpactAssessment"},
		{"no roles", "", "", true, nil, "CCEO"},
		{"nobody", "", "", false, nil, "CCEO"},
	}
	for _, tt := range tests {
		if got := ownerRoleOf(tt.stamped, tt.found, tt.active, tt.roles); got != tt.want {
			t.Fatalf("%s: got %q, want %q", tt.name, got, tt.want)
		}
	}
}

// _notify_weekly_approver's body: "%b %d" days and the total with commas.
func TestTheApproverIsToldTheWeekAndItsTotal(t *testing.T) {
	start := time.Date(2026, 12, 7, 0, 0, 0, 0, time.UTC)
	got := weekSubmittedBody(start, start.AddDate(0, 0, 6), 1234000)
	want := "A weekly fund request (Dec 07 – Dec 13, UGX 1,234,000) needs your review."
	if got != want {
		t.Fatalf("got %q\nwant %q", got, want)
	}
}

// The existing service's refusals, word for word, as the page shows them.
func TestTheOwnersWeekRefusalsAreTheExistingWords(t *testing.T) {
	tests := []struct {
		op, answer, want string
	}{
		{weekSend, "gone", "Weekly fund request not found."},
		{weekSend, "not_owner", "Only the owner can confirm this request."},
		{weekSend, "status:submitted_to_pl", "Cannot request advance in status 'submitted_to_pl'."},
		{weekSkip, "not_owner", "Only the owner can confirm this request."},
		{weekSkip, "paid", "Cannot cancel a disbursed request."},
		{weekReceipt, "not_owner", "Only the owner can confirm receipt of these funds."},
		{weekReceipt, "not_disbursed", "These funds are not marked as disbursed."},
		{weekReceipt, "no_bank", "Confirm only after receiving the bank message and verifying the funds arrived."},
	}
	for _, tt := range tests {
		err := weekRefusal(tt.op, tt.answer)
		var r *Refusal
		if !errors.As(err, &r) || r.Message != tt.want {
			t.Fatalf("%s %s: got %v, want %q", tt.op, tt.answer, err, tt.want)
		}
	}
	if err := weekRefusal(weekSend, "submitted_to_pl"); err != nil {
		t.Fatalf("a new status is no refusal: %v", err)
	}
}

// The views' own words once the save is made.
func TestTheOwnersWeekSavesSayWhatTheViewsSay(t *testing.T) {
	for op, want := range map[string]string{
		weekSend:     "Weekly advance request submitted for supervisor approval.",
		weekSelfFund: "Self Fund request sent for approval.",
		weekSkip:     "No advance will be requested for this week.",
		weekReceipt:  "Receipt confirmed — you can now account for this week's spend.",
	} {
		if got := weekSavedMessage(op); got != want {
			t.Fatalf("%s = %q, want %q", op, got, want)
		}
	}
}

// The page's form keys name the save.
func TestAnOwnersWeekFormNamesItsSave(t *testing.T) {
	for path, want := range map[string][2]string{
		"/fund-requests/weekly/abc123/confirm":         {"abc123", weekSend},
		"/fund-requests/weekly/abc123/self-funded":     {"abc123", weekSelfFund},
		"/fund-requests/weekly/abc123/not-requested":   {"abc123", weekSkip},
		"/fund-requests/weekly/abc123/confirm-receipt": {"abc123", weekReceipt},
	} {
		id, op, ok := WeekOwnerForm(path)
		if !ok || id != want[0] || op != want[1] {
			t.Fatalf("%s = %q %q %v", path, id, op, ok)
		}
	}
	for _, path := range []string{"/fund-requests/weekly/abc/approve", "/fund-requests/weekly", "/fund-requests/weekly/a/b/confirm"} {
		if _, _, ok := WeekOwnerForm(path); ok {
			t.Fatalf("%s should not be an owner's form", path)
		}
	}
}
