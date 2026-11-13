package calendarpage

import (
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// Days are dates at midnight UTC, as pgx reads a date column.

func day(year int, month time.Month, d int) time.Time {
	return time.Date(year, month, d, 0, 0, 0, 0, time.UTC)
}

// localDay is clock.local_day: the day an instant falls on in the
// project's time zone (a day picked in a drawer is saved as local midnight,
// 21:00 UTC the day before).
func localDay(t time.Time) time.Time {
	l := t.In(location)
	return day(l.Year(), l.Month(), l.Day())
}

func later(a, b time.Time) time.Time {
	if a.After(b) {
		return a
	}
	return b
}

func earlier(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}

// collapse is the feed's reading of a text: its whitespace run together.
func collapse(s string) string { return closedschools.PyCollapse(s) }

// casefold is str.casefold for the names the page compares.
func casefold(s string) string { return strings.ToLower(s) }

// pyTitle is Python's str.title(): each run of cased letters starts upper
// case and goes on lower case.
func pyTitle(s string) string {
	var b strings.Builder
	cased := false
	for _, r := range s {
		isCased := unicode.IsUpper(r) || unicode.IsLower(r) || unicode.IsTitle(r)
		switch {
		case isCased && !cased:
			b.WriteRune(unicode.ToTitle(r))
		case isCased:
			b.WriteRune(unicode.ToLower(r))
		default:
			b.WriteRune(r)
		}
		cased = isCased
	}
	return b.String()
}

// rangeLabel is _calendar_range_label: "12–14 August 2026",
// "30 July – 2 August 2026".
func rangeLabel(start, end time.Time) string {
	d := func(t time.Time) string { return itoa(t.Day()) }
	switch {
	case start.Equal(end):
		return d(start) + " " + start.Month().String() + " " + itoa(start.Year())
	case start.Year() == end.Year() && start.Month() == end.Month():
		return d(start) + "–" + d(end) + " " + start.Month().String() + " " + itoa(start.Year())
	case start.Year() == end.Year():
		return d(start) + " " + start.Month().String() + " – " + d(end) + " " + end.Month().String() + " " + itoa(end.Year())
	}
	return d(start) + " " + start.Month().String() + " " + itoa(start.Year()) + " – " +
		d(end) + " " + end.Month().String() + " " + itoa(end.Year())
}

// shortDay is strftime("%a %-d %b").
func shortDay(t time.Time) string { return t.Format("Mon 2 Jan") }

// longDay is the template's date:"l j F".
func longDay(t time.Time) string { return t.Format("Monday 2 January") }

func itoa(n int) string { return strconv.Itoa(n) }

// strip is Python's str.strip().
func strip(s string) string { return closedschools.PyStrip(s) }
