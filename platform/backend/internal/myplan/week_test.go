package myplan

import (
	"testing"
	"time"
)

func dayOf(s string) time.Time {
	d, err := time.Parse(time.DateOnly, s)
	if err != nil {
		panic(err)
	}
	return d
}

func TestWeekStatusReadsTheStateAndWhatItAsks(t *testing.T) {
	today := dayOf("2026-11-16")
	yesterday, tomorrow := dayOf("2026-11-15"), dayOf("2026-11-17")
	complete := completion{salesforce: "SVE-1", evidenceOK: true}
	cases := []struct {
		status  string
		day     time.Time
		c       completion
		key     string
		label   string
		done    bool
		open    bool
		asks    string
		comment string
	}{
		{"ia_verified", tomorrow, complete, "verified", "Verified", true, false, "none", "verified with both halves"},
		{"ia_verified", tomorrow, completion{evidenceOK: true}, "incomplete", "Missing Salesforce ID", false, true, "none", "verified without its ID"},
		{"submitted_to_pl", tomorrow, complete, "awaiting_you", "Awaiting your verification", true, true, "verify", "with the lead"},
		{"in_progress", yesterday, completion{}, "started", "In Progress", false, true, "send", "under way"},
		{"returned_by_pl", tomorrow, completion{}, "returned", "Returned", false, true, "send", "returned"},
		{"scheduled", yesterday, completion{}, "past_due", "Past Due", false, true, "send", "past its day"},
		{"scheduled", today, completion{}, "today", "Due today", false, true, "send", "due today"},
		{"scheduled", tomorrow, completion{}, "scheduled", "Scheduled", false, true, "send", "ahead"},
	}
	for _, c := range cases {
		d := c.day
		s := weekStatus(c.status, &d, today, c.c)
		if s.key != c.key || s.label != c.label || s.done != c.done || s.open != c.open || s.action != c.asks {
			t.Errorf("%s: %+v, want %s %q done=%v open=%v %s", c.comment, s, c.key, c.label, c.done, c.open, c.asks)
		}
	}
}

func TestResolveWeekOpensOnAMondayWithinReach(t *testing.T) {
	today := dayOf("2026-11-18")
	cases := map[string]string{
		"":                 "2026-11-16",
		"nonsense":         "2026-11-16",
		"2026-11-12":       "2026-11-09",
		" 2026-11-25 ":     "2026-11-23",
		"2026-11-25T10:00": "2026-11-23",
		"2020-01-06":       "2026-11-16",
	}
	for raw, want := range cases {
		if got := ResolveWeek(raw, today).Format(time.DateOnly); got != want {
			t.Errorf("%q: %s, want %s", raw, got, want)
		}
	}
}

func TestWeekRangeNamesTheMonthOnceWhenItCan(t *testing.T) {
	cases := map[string]string{
		"2026-11-16": "16–22 November 2026",
		"2026-11-30": "30 Nov – 6 Dec 2026",
		"2026-12-28": "28 Dec 2026 – 3 Jan 2027",
	}
	for start, want := range cases {
		s := dayOf(start)
		if got := (Week{Start: s, End: s.AddDate(0, 0, 6)}).rangeLabel(); got != want {
			t.Errorf("%s: %q, want %q", start, got, want)
		}
	}
}
