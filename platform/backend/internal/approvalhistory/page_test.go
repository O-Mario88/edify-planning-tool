package approvalhistory

import (
	"testing"
	"time"
)

func TestTheWeekIsTheCalendarYearAndTheISOWeek(t *testing.T) {
	for day, want := range map[string]string{
		"2026-04-27": "2026-W18",
		"2027-01-01": "2027-W53", // ISO week 53 of 2026; the filter's Y is the calendar year
		"2024-12-30": "2024-W1",
	} {
		d, err := time.Parse(time.DateOnly, day)
		if err != nil {
			t.Fatal(err)
		}
		if got := weekLabel(d); got != want {
			t.Errorf("weekLabel(%s) = %q, want %q", day, got, want)
		}
	}
}

func TestTheStatusIsWordsWithTheInitialismsKept(t *testing.T) {
	for status, want := range map[string]string{
		"pending_responsible_confirmation": "Pending Responsible Confirmation",
		"returned_by_pl":                   "Returned By PL",
		"submitted-to-cd":                  "Submitted To CD",
		"":                                 "",
	} {
		if got := statusLabel(status); got != want {
			t.Errorf("statusLabel(%q) = %q, want %q", status, got, want)
		}
	}
}

func TestTheChainFollowsTheStatus(t *testing.T) {
	for status, want := range map[string][3]string{
		"pending_responsible_confirmation": {"pending", "not_started", "not_started"},
		"confirmed_for_advance":            {"approved", "pending", "not_started"},
		"accounted":                        {"approved", "approved", "done"},
		"returned_by_accountant":           {"approved", "returned", "not_started"},
		"rejected":                         {"approved", "not_started", "not_started"},
	} {
		if got := chain(status); got != want {
			t.Errorf("chain(%q) = %v, want %v", status, got, want)
		}
	}
}
