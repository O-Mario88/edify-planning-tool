package activities

import (
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"testing"
	"time"
)

// A session's ID entry refuses a day after today in completion_day's words,
// where the Complete drawer hands it on; today, an earlier day and none are
// the day done.
func TestASessionsCompletedDayIsReadAsTheViewReadsIt(t *testing.T) {
	s := &Service{kampala: time.UTC, now: func() time.Time { return time.Date(2026, 11, 25, 9, 0, 0, 0, time.UTC) }}
	today := time.Date(2026, 11, 25, 0, 0, 0, 0, time.UTC)
	for raw, want := range map[string]time.Time{"": today, "2026-11-25": today, " 2026-11-03 ": time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)} {
		got, err := s.sessionCompletedOn(raw)
		if err != nil || !got.Equal(want) {
			t.Errorf("%q: %v %v, want %v", raw, got, err, want)
		}
	}
	_, err := s.sessionCompletedOn("2026-11-26")
	var refusal *Refusal
	if !errors.As(err, &refusal) || refusal.Message != futureDayRefusal {
		t.Errorf("tomorrow: %v, want the refusal %q", err, futureDayRefusal)
	}
}

// The function that hands a session in with its ID takes the statuses the
// Go save starts or hands in, as the meeting's completion does.
func TestTheSessionIDHandInTakesTheStartableStatuses(t *testing.T) {
	raw, err := os.ReadFile(filepath.FromSlash("../../../deploy/db/completion_roles.sql"))
	if err != nil {
		t.Fatal(err)
	}
	fn := regexp.MustCompile(`(?s)FUNCTION gateway_completion\.hand_in_session_with_id\(.*?\$fn\$;`).Find(raw)
	array := regexp.MustCompile(`(?s)work\.status = ANY \(ARRAY\[(.*?)\]::varchar\[\]\)`).FindSubmatch(fn)
	if array == nil {
		t.Fatal("the function's statuses were not found")
	}
	named := []string{}
	for _, m := range regexp.MustCompile(`'([a-z_]+)'`).FindAllSubmatch(array[1], -1) {
		named = append(named, string(m[1]))
	}
	want := append(slices.Clone(startableStatuses), startedStatus)
	slices.Sort(named)
	slices.Sort(want)
	if !slices.Equal(named, want) {
		t.Fatalf("the function takes %v; the Go save takes %v", named, want)
	}
}
