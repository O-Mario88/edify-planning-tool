package clusterlead

import "testing"

func TestASchoolsProgressIsItsLinkedActivitysOwnState(t *testing.T) {
	cases := []struct {
		status, activity string
		linked           bool
		want             string
	}{
		{schoolAwaiting, "", false, schoolAwaiting},
		{schoolAccepted, "", false, schoolAccepted},
		{schoolAccepted, "scheduled", true, progressPlanned},
		{schoolAccepted, "partner_scheduled", true, progressPlanned},
		{schoolAccepted, "in_progress", true, progressInProgress},
		// Evidence submitted is never verification (brief 18.15).
		{schoolAccepted, "evidence_uploaded", true, progressImplemented},
		{schoolAccepted, "awaiting_ia_verification", true, progressImplemented},
		{schoolAccepted, "completed", true, progressVerified},
		{schoolAccepted, "ia_verified", true, progressVerified},
		{schoolAccepted, "cancelled", true, progressReplanNeeded},
		// A returned school stays returned whatever was linked.
		{schoolReturned, "completed", true, schoolReturned},
	}
	for _, c := range cases {
		if got := schoolProgress(c.status, c.activity, c.linked); got != c.want {
			t.Errorf("%s + %q: %s, want %s", c.status, c.activity, got, c.want)
		}
	}
}

func TestOneSchoolsVerifiedSupportNeverMarksTheActionDone(t *testing.T) {
	key, _, _, summary := actionOverall("submitted", []string{progressVerified, progressPlanned, schoolAwaiting, progressVerified, "returned"})
	if key != schoolAwaiting || summary != "2 of 5 schools verified" {
		t.Fatalf("partial progress reads %q (%q)", key, summary)
	}
	key, _, _, _ = actionOverall("submitted", []string{progressVerified, schoolDeclined})
	if key != "review_due" {
		t.Fatalf("every school finished: %q", key)
	}
	if tab := actionTab("submitted", []string{progressVerified, schoolDeclined}); tab != "open" {
		t.Fatalf("a finished action waits for the leader's review: %q", tab)
	}
}

func TestTheRegisterTabsFollowWhoseMoveItIs(t *testing.T) {
	cases := []struct {
		status  string
		schools []string
		want    string
	}{
		{"draft", []string{schoolDraft}, "open"},
		{"submitted", []string{schoolAwaiting}, "waiting"},
		{"submitted", []string{schoolClarification, progressPlanned}, "open"},
		{"submitted", []string{schoolReturned, progressPlanned}, "open"},
		{"submitted", []string{progressInProgress}, "waiting"},
		{"closed", []string{progressVerified}, "completed"},
		{"cancelled", []string{schoolCancelled}, "completed"},
	}
	for _, c := range cases {
		if got := actionTab(c.status, c.schools); got != c.want {
			t.Errorf("%s %v: %s, want %s", c.status, c.schools, got, c.want)
		}
	}
}

func TestStaffQueuesFollowProgressAndOverdue(t *testing.T) {
	if q := supportQueue(schoolAwaiting, false); q != "new" {
		t.Fatal(q)
	}
	if q := supportQueue(progressPlanned, true); q != "overdue" {
		t.Fatal(q)
	}
	if q := supportQueue(progressVerified, true); q != "completed" {
		t.Fatalf("verified support is never overdue: %s", q)
	}
}

func TestReferencesAreShortAndUnambiguous(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		ref, err := newRef()
		if err != nil || len(ref) != 9 || ref[:3] != "CA-" {
			t.Fatalf("ref %q %v", ref, err)
		}
		for _, c := range ref[3:] {
			if c == '0' || c == 'O' || c == '1' || c == 'I' {
				t.Fatalf("ambiguous character in %q", ref)
			}
		}
		seen[ref] = true
	}
	if len(seen) < 195 {
		t.Fatalf("references repeat too often: %d distinct of 200", len(seen))
	}
}
