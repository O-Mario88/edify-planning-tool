package todos

import (
	"testing"
	"time"
)

// The existing To-Do builders mix the UTC day and year with Kampala's local
// day: from 21:00 UTC (midnight in Kampala) a reader's year, a Salesforce
// submission's day and a returned hand-over's due day were a day (or on 30
// September a year) behind. Go reads Kampala's day everywhere (owner,
// 2026-11-13: "Can you fix those from the go side").
func TestToDoDaysAndYearsAreKampalasDay(t *testing.T) {
	late := time.Date(2026, time.September, 30, 22, 0, 0, 0, time.UTC) // 01:00 on 1 October in Kampala
	if got := readerYear(late); got != "2027" {
		t.Fatalf("the reader's year at 22:00 UTC on 30 September: %s, want 2027", got)
	}
	if got := localDate(late); !got.Equal(time.Date(2026, time.October, 1, 0, 0, 0, 0, time.UTC)) {
		t.Fatalf("a time's day: %v, want 1 October", got)
	}
	early := time.Date(2026, time.September, 30, 12, 0, 0, 0, time.UTC)
	if got := readerYear(early); got != "2026" {
		t.Fatalf("at noon on 30 September: %s, want 2026", got)
	}
}
