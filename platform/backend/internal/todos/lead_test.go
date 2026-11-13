package todos

import (
	"testing"
	"time"
)

func onDay(y int, m time.Month, d int) *time.Time {
	t := time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	return &t
}

// reviewer_todos over team_review_rows: priorities waiting on the reviewer
// (overdue when the agreement itself is late, and then not raised twice),
// every other review past its date and not finished, nothing for a finished
// or closed review; an open conversation passes the reader on.
func TestReviewerRowsAreTheExistingOnes(t *testing.T) {
	name := "Deo M."
	r := &reader{today: *onDay(2026, 11, 13)}
	people := []reviewee{{staffID: "s1", name: &name}, {staffID: "s2", name: nil}}
	annual := rules.TargetReviewType
	reviews := []review{
		{id: "a1", staffID: "s1", reviewType: annual, stage: rules.Lead.ReviewStageManagerReview, status: "x", due: onDay(2026, 11, 1)},
		{id: "q1", staffID: "s1", reviewType: "quarterly", stage: "x", status: "x", due: onDay(2026, 11, 12)},
		{id: "q2", staffID: "s1", reviewType: "quarterly", stage: "x", status: "x", due: onDay(2026, 11, 13)},
		{id: "q3", staffID: "s1", reviewType: "quarterly", stage: rules.Lead.ReviewDoneStages[0], status: "x", due: onDay(2026, 1, 1)},
		{id: "q4", staffID: "s1", reviewType: "quarterly", stage: "x", status: rules.Lead.ReviewClosedStatuses[1], due: onDay(2026, 1, 1)},
		{id: "q5", staffID: "s1", reviewType: "quarterly", stage: "x", status: "x"},
		{id: "a2", staffID: "s2", reviewType: annual, stage: "priorities_draft", status: "x"},
	}
	got, err := reviewRows(r, people, reviews, "priority_setting")
	if err != nil {
		t.Fatal(err)
	}
	want := []struct{ title, status, priority string }{
		{"Review Deo M.'s priorities", "overdue", "high"},
		{"Complete Deo M.'s overdue performance review", "overdue", "high"},
	}
	if len(got) != len(want) {
		t.Fatalf("%d rows: %+v", len(got), got)
	}
	for i, w := range want {
		if got[i].Title != w.title || got[i].StatusKey != w.status || got[i].Priority != w.priority ||
			got[i].ActionURL != "/performance-conversation?staff=s1" {
			t.Errorf("row %d: %+v", i, got[i])
		}
	}
	if !got[0].Due.Equal(*onDay(2026, 11, 1)) || !got[1].Due.Equal(*onDay(2026, 11, 12)) {
		t.Errorf("due %v %v", got[0].Due, got[1].Due)
	}
	// Waiting, not late: medium, due today for the sort.
	reviews[0].due = onDay(2026, 12, 1)
	got, _ = reviewRows(r, people[:1], reviews[:1], "none")
	if len(got) != 1 || got[0].Priority != "medium" || got[0].StatusKey != "waiting_me" || !got[0].Due.Equal(r.today) {
		t.Errorf("waiting %+v", got)
	}
	// A conversation window open on an agreed review is passed on.
	reviews[0].stage = "agreed"
	if _, err := reviewRows(r, people[:1], reviews[:1], rules.Lead.ConversationWindows[0]); err != errPassOn {
		t.Errorf("open window: %v", err)
	}
	// None in a name prints as Python does.
	reviews[6].stage = rules.Lead.ReviewStageManagerReview
	got, _ = reviewRows(r, people[1:], reviews[6:], "none")
	if len(got) != 1 || got[0].Title != "Review None's priorities" {
		t.Errorf("no name %+v", got)
	}
}

func TestTheOneToOneLinkIsUrlencoded(t *testing.T) {
	q := map[string][]string{"open": {"new"}, "cceo": {"a b&c"}, "kind": {"one_to_one"}}
	if got := pyURLEncode(q, "open", "cceo", "kind"); got != "open=new&cceo=a+b%26c&kind=one_to_one" {
		t.Error(got)
	}
}
