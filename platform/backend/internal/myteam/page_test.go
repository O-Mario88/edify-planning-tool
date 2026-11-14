package myteam

import (
	"testing"
	"time"
)

func day(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func TestTheWaitingLineNamesEachHandoff(t *testing.T) {
	if got := waitingText(map[string]int{}); got != "Nothing" {
		t.Errorf("%q", got)
	}
	got := waitingText(map[string]int{"completions": 1, "development": 2, "leave": 1, "escalations": 3, "extra_work": 2})
	if want := "1 completion · 2 PD requests · 1 leave request · 3 escalations · 2 extra work"; got != want {
		t.Errorf("%q, want %q", got, want)
	}
}

func TestDueAndWaitingWords(t *testing.T) {
	today := day(2026, time.November, 14)
	for target, want := range map[time.Time]string{
		day(2026, time.October, 31): "14 days overdue", today: "due today",
		day(2026, time.November, 15): "due tomorrow", day(2026, time.November, 20): "in 6 days",
	} {
		if got := dueLabel(target, today); got != want {
			t.Errorf("%v: %q, want %q", target, got, want)
		}
	}
	if daysAgo(0) != "today" || daysAgo(1) != "1 day" || daysAgo(8) != "8 days" {
		t.Error("days ago")
	}
}

func TestCoachingAndLeaveCells(t *testing.T) {
	held := day(2026, time.November, 5)
	all := map[string]coaching{
		"a": {heldOn: &held, kind: "one_to_one", shared: true, followUp: true},
		"b": {heldOn: &held, kind: "recognition", shared: true},
		"c": {},
	}
	for id, want := range map[string]string{
		"a": "5 Nov · Monthly one-to-one · follow-up open", "b": "5 Nov · Recognition · not acknowledged",
		"c": "Coached", "d": "Not coached yet",
	} {
		if got := coachingCell(all, id); got != want {
			t.Errorf("%s: %q, want %q", id, got, want)
		}
	}
	l := leave{awayNow: map[string]time.Time{"a": day(2026, time.November, 17)}, nextAway: map[string]time.Time{"b": day(2026, time.December, 1)}}
	if text, away := leaveCell(l, "a"); text != "On leave until 17 Nov" || !away {
		t.Errorf("%q %v", text, away)
	}
	if text, _ := leaveCell(l, "b"); text != "Away from 1 Dec" {
		t.Errorf("%q", text)
	}
	if text, _ := leaveCell(l, "c"); text != "—" {
		t.Errorf("%q", text)
	}
}
