package activities

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The note's dates are Python's isoformat: the stored UTC instant and the
// new Kampala midnight (costs_follow.reschedule_note).
func TestPyISOWritesPythonsIsoformat(t *testing.T) {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		t.Fatal(err)
	}
	cases := map[string]time.Time{
		"2026-11-16T21:00:00+00:00":        time.Date(2026, 11, 16, 21, 0, 0, 0, time.UTC),
		"2026-11-26T00:00:00+03:00":        time.Date(2026, 11, 26, 0, 0, 0, 0, kampala),
		"2026-11-16T21:00:00.123456+00:00": time.Date(2026, 11, 16, 21, 0, 0, 123456000, time.UTC),
	}
	for want, at := range cases {
		if got := pyISO(at); got != want {
			t.Errorf("pyISO(%v) = %q, want %q", at, got, want)
		}
	}
}

func TestSameDayComparesTheCalendarDay(t *testing.T) {
	a := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)
	if !sameDay(a, a.Add(23*time.Hour)) || sameDay(a, a.AddDate(0, 0, 1)) {
		t.Fatal("sameDay")
	}
}

// The move's vocabulary comes from rules.json, never restated.
func TestTheMoveRulesAreExported(t *testing.T) {
	if rules.Move.SavedMessage != "Saved. Press Refresh to see it on the page." ||
		rules.Move.OverdueEvent == "" || rules.Move.DayOffEvent == "" {
		t.Fatalf("move rules: %+v", rules.Move)
	}
}

// A person in an acting seat, with no staff profile, or asking for visits,
// is handed on before anything is read.
func TestTheMoveIsHandedOnBeforeAnyRead(t *testing.T) {
	s, err := NewService(nil, nil, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	for name, p := range map[string]auth.Principal{
		"acting":           {Account: auth.Account{StaffProfileID: "s", InActingAppointment: true}},
		"no staff profile": {Account: auth.Account{}},
	} {
		_, err := s.prepareMove(context.Background(), p, MoveRequest{ActivityID: "a", Date: "2026-11-20"}, Origin{})
		if !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v, want a hand-on", name, err)
		}
	}
}
