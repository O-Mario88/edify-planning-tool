package planningmonitor

import (
	"testing"
	"time"
)

// ended_windows and due_windows: on a Wednesday in November the last week,
// October, the year's last quarter and the last year have ended; only the
// week is within the fortnight its close may be taken in.
func TestDueSnapshotWindowsAreTheRecentlyEndedPeriods(t *testing.T) {
	today := time.Date(2026, 11, 25, 0, 0, 0, 0, time.UTC)
	ended := endedWindows(today)
	want := [][3]string{{"week", "2026-11-16", "2026-11-23"}, {"month", "2026-10-01", "2026-11-01"},
		{"quarter", "2026-07-01", "2026-10-01"}, {"fy", "2025-10-01", "2026-10-01"}}
	for i, w := range ended {
		if got := [3]string{w.period, w.start.Format(time.DateOnly), w.end.Format(time.DateOnly)}; got != want[i] {
			t.Errorf("window %d: %v, want %v", i, got, want[i])
		}
	}
	due := DueSnapshotWindows(today)
	if len(due) != 1 || due[0].Period() != "week" || due[0].Label() != "Week of 16 Nov 2026" {
		t.Fatalf("due %v", due)
	}
	// On the first of the month the month just ended is due, and on 1
	// October the quarter and the year too.
	if n := len(DueSnapshotWindows(time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC))); n != 4 {
		t.Fatalf("on 1 October: %d due, want 4", n)
	}
}
