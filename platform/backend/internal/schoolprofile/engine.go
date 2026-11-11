package schoolprofile

import (
	"math"
	"strconv"
	"time"
)

// The profile engine (apps.analytics.profile_intelligence and
// profile_records) over one school: the year a profile reads, the part of
// it the work is read for, and the arithmetic the existing figures use.

// pySum is Python's sum() of floats (3.12 and later): Neumaier's
// compensated summation, as CPython does it.
func pySum(values []float64) float64 {
	total, c := 0.0, 0.0
	for _, x := range values {
		t := total + x
		if math.Abs(total) >= math.Abs(x) {
			c += (total - t) + x
		} else {
			c += (x - t) + total
		}
		total = t
	}
	if c != 0 && !math.IsInf(c, 0) && !math.IsNaN(c) {
		total += c
	}
	return total
}

// pyRound is Python's round(x, n) for a float: correctly rounded from the
// exact binary value, ties to even.
func pyRound(x float64, n int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', n, 64), 64)
	return v
}

// pyMean is the engine's _mean: the mean of the values given, rounded to two
// places; nil for none.
func pyMean(values []*float64) *float64 {
	present := []float64{}
	for _, v := range values {
		if v != nil {
			present = append(present, *v)
		}
	}
	if len(present) == 0 {
		return nil
	}
	m := pyRound(pySum(present)/float64(len(present)), 2)
	return &m
}

// fyLabel is year_comparison.fy_label: "FY 2025/26" for the year ending 2026.
func fyLabel(fy string) string {
	end, err := strconv.Atoi(fy)
	if err != nil {
		return "FY " + fy
	}
	s := strconv.Itoa(end)
	return "FY " + strconv.Itoa(end-1) + "/" + s[len(s)-2:]
}

func previousFY(fy string) string {
	end, err := strconv.Atoi(fy)
	if err != nil {
		return ""
	}
	return strconv.Itoa(end - 1)
}

// fyChoices is profile_views.fy_choices: the running year and the two
// before it.
func fyChoices(running string) []string {
	end, _ := strconv.Atoi(running)
	return []string{strconv.Itoa(end), strconv.Itoa(end - 1), strconv.Itoa(end - 2)}
}

var (
	fyMonths   = []string{"Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"}
	quarterOf  = []string{"Q1", "Q2", "Q3", "Q4"}
	quarterSay = map[string]string{"Q1": "Oct–Dec", "Q2": "Jan–Mar", "Q3": "Apr–Jun", "Q4": "Jul–Sep"}
)

// periodOptions is profile_intelligence.period_options: the whole year, a
// quarter, a month.
func periodOptions() [][2]string {
	out := [][2]string{{"", "Full year"}}
	for _, q := range quarterOf {
		out = append(out, [2]string{q, q + " (" + quarterSay[q] + ")"})
	}
	for i, m := range fyMonths {
		out = append(out, [2]string{"M" + strconv.Itoa(i+1), m})
	}
	return out
}

func knownPeriod(period string) bool {
	for _, o := range periodOptions() {
		if o[0] == period {
			return true
		}
	}
	return false
}

// window is the part of a year the work is read for: [start, end) as
// calendar days, and its words; a zero start is the whole year.
type window struct {
	start, end time.Time
	label      string
}

func (w window) whole() bool { return w.start.IsZero() }

// periodWindow is profile_intelligence.period_window.
func periodWindow(fy, period string) window {
	end, err := strconv.Atoi(fy)
	if err != nil {
		return window{}
	}
	day := func(y int, m time.Month) time.Time { return time.Date(y, m, 1, 0, 0, 0, 0, time.UTC) }
	switch {
	case quarterSay[period] != "":
		q, _ := strconv.Atoi(period[1:])
		start := day(end, time.Month(1+3*(q-2)))
		if q == 1 {
			start = day(end-1, time.October)
		}
		return window{start: start, end: start.AddDate(0, 3, 0), label: period + " (" + quarterSay[period] + ")"}
	case len(period) > 1 && period[0] == 'M':
		m, err := strconv.Atoi(period[1:])
		if err != nil || m < 1 || m > 12 {
			return window{}
		}
		start := day(end-1, time.October).AddDate(0, m-1, 0)
		return window{start: start, end: start.AddDate(0, 1, 0), label: fyMonths[m-1] + " " + strconv.Itoa(start.Year())}
	}
	return window{}
}

// sql is profile_intelligence._in_window over an activity a: its planned
// day, else the day it was scheduled for on Kampala's clock (Django's
// scheduled_date__date reads the current time zone). It adds its two
// arguments to args and returns the clause, "true" for the whole year.
func (w window) sql(args *[]any) string {
	if w.whole() {
		return "true"
	}
	*args = append(*args, w.start, w.end)
	s, e := "$"+strconv.Itoa(len(*args)-1), "$"+strconv.Itoa(len(*args))
	return "((a.planned_date >= " + s + "::date AND a.planned_date < " + e + "::date) OR (a.planned_date IS NULL AND " +
		"(a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date >= " + s + "::date AND " +
		"(a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < " + e + "::date))"
}
