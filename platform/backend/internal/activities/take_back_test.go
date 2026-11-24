package activities

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

func TestAWeekIsFiledUnderItsMonday(t *testing.T) {
	for day, want := range map[string]string{
		"2026-12-07": "2026-12-07", "2026-12-09": "2026-12-07", "2026-12-13": "2026-12-07", "2026-12-14": "2026-12-14",
	} {
		parsed, _ := time.Parse(time.DateOnly, day)
		if got := mondayOf(parsed).Format(time.DateOnly); got != want {
			t.Fatalf("%s = %s, want %s", day, got, want)
		}
	}
}

func TestAWeekIsNamedByItsDays(t *testing.T) {
	start := time.Date(2026, 12, 7, 0, 0, 0, 0, time.UTC)
	if got := weekLabel(start, start.AddDate(0, 0, 6)); got != "7 Dec – 13 Dec" {
		t.Fatalf("got %q", got)
	}
}

// plan_changes._notify_owner: what the owner reads, by how the request stood.
func TestTheOwnerIsToldWhyTheRequestCameBack(t *testing.T) {
	tests := []struct {
		name, was string
		still     bool
		want      string
	}{
		{"sent", "submitted_to_pl", true, "Visit at X changed after the fund request for 7 Dec – 13 Dec was sent, so the request " +
			"has come back to you with the new figures. Send it for approval again."},
		{"no advance", "not_requested", true, "Visit at X changed in 7 Dec – 13 Dec, a week you had set to No Advance. The " +
			"week's request is open again with the new figures: send it for approval, or choose No Advance again."},
		{"withdrawn", "confirmed_for_advance", false, "Visit at X changed after the fund request for 7 Dec – 13 Dec was " +
			"sent. Nothing is left to fund in that week, so the request has been withdrawn."},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := takenBackOwnerBody("Visit at X", "7 Dec – 13 Dec", tt.was, tt.still); got != tt.want {
				t.Fatalf("got %q", got)
			}
		})
	}
}

func TestWhoeverHadTheRequestIsToldWhatTheyNoLongerDo(t *testing.T) {
	for was, want := range map[string]string{
		"submitted_to_pl": "approve", "submitted_to_cd": "approve", "confirmed_for_advance": "disburse", "not_requested": "",
	} {
		if got := takenBackWaiting(was); got != want {
			t.Fatalf("%s = %q", was, got)
		}
	}
	got := takenBackReviewerBody("Paul N.", "7 Dec – 13 Dec", 36000, "Visit at X", "approve")
	want := "Paul N.'s fund request for 7 Dec – 13 Dec (UGX 36,000) went back to them because Visit at X in that week " +
		"changed. There is nothing to approve until it is sent again with the new figures."
	if got != want {
		t.Fatalf("got %q", got)
	}
}

// The owner opens the request to send it again; a reviewer goes to the list.
func TestATakenBackNoticeLinksToTheRequestOrTheList(t *testing.T) {
	if r := takenBackRecipient("u1", "w1"); r.route != "/fund-requests/weekly/w1" || r.label != "Send Fund Request" {
		t.Fatalf("got %+v", r)
	}
	if r := takenBackRecipient("u2", ""); r.route != "/fund-requests/weekly" || r.label != "View Fund Requests" {
		t.Fatalf("got %+v", r)
	}
}

func TestANoticeIsNormalUnlessItAsks(t *testing.T) {
	if (scheduledNotice{}).level() != "normal" || (scheduledNotice{priority: "high"}).level() != "high" {
		t.Fatal("the notice's priority is wrong")
	}
}

func TestTheHandInNamesTheWorkAsTheExistingApplicationDoes(t *testing.T) {
	for value, want := range map[string]string{"story_gathering_visit": "Gathering Story", "donor_visit": "Donor Visit"} {
		if got := myplan.TypeLabel(value); got != want {
			t.Fatalf("%s = %q, want %q", value, got, want)
		}
	}
}
