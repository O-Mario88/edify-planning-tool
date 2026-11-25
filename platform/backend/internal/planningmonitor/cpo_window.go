package planningmonitor

import (
	"fmt"
	"strconv"
	"time"
)

// cpoZone is TIME_ZONE: the day an activity's scheduled moment falls on
// (TruncDate) and a hand-over's local day.
const cpoZone = "Africa/Nairobi"

var cpoLocation = func() *time.Location {
	l, err := time.LoadLocation(cpoZone)
	if err != nil {
		panic("planningmonitor: " + err.Error())
	}
	return l
}()

// cpoWindow is coverage.Window: the slice of a fiscal year read; end is
// exclusive.
type cpoWindow struct {
	fy, period, quarter, week string
	month                     int
	start, end                time.Time
	fyStart, fyEnd            time.Time
	monthsOfFY                []int
}

func (w cpoWindow) isAnnual() bool          { return w.period == "fy" }
func (w cpoWindow) hasPhasedTarget() bool   { return w.period == "quarter" || w.period == "month" }
func (w cpoWindow) inside(d time.Time) bool { return !d.Before(w.start) && d.Before(w.end) }

// bucket is _bucket: 0 before the window, 1 inside, 2 after.
func (w cpoWindow) bucket(d time.Time) int {
	switch {
	case d.Before(w.start):
		return 0
	case d.Before(w.end):
		return 1
	}
	return 2
}

func date(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

// fyMonthIndex is _fy_month_index: October is 1.
func fyMonthIndex(calendarMonth int) int {
	if calendarMonth >= 10 {
		return calendarMonth - 9
	}
	return calendarMonth + 3
}

var quarterStart = map[string]time.Month{"Q1": time.October, "Q2": time.January, "Q3": time.April, "Q4": time.July}

// cpoWindowFor is window_for.
func cpoWindowFor(fy, period, quarter string, month int, weekStart *time.Time) cpoWindow {
	n, _ := strconv.Atoi(fy)
	fyStart, fyEnd := date(n-1, time.October, 1), date(n, time.October, 1)
	w := cpoWindow{fy: fy, period: "fy", start: fyStart, end: fyEnd, fyStart: fyStart, fyEnd: fyEnd}
	switch {
	case period == "quarter" && quarterStart[quarter] != 0:
		year := n
		if quarter == "Q1" {
			year = n - 1
		}
		w.period, w.quarter = "quarter", quarter
		w.start = date(year, quarterStart[quarter], 1)
		w.end = w.start.AddDate(0, 3, 0)
		first := fyMonthIndex(int(w.start.Month()))
		w.monthsOfFY = []int{first, first + 1, first + 2}
	case period == "month" && month >= 1 && month <= 12:
		year := fyEnd.Year()
		if month >= 10 {
			year = fyStart.Year()
		}
		w.period, w.month = "month", month
		w.start = date(year, time.Month(month), 1)
		w.end = w.start.AddDate(0, 1, 0)
		w.monthsOfFY = []int{fyMonthIndex(month)}
	case period == "week" && weekStart != nil:
		w.period = "week"
		w.start, w.end = *weekStart, weekStart.AddDate(0, 0, 7)
		y, wk := weekStart.ISOWeek()
		w.week = strconv.Itoa(y) + "-W" + twoDigits(wk)
	default:
		w.monthsOfFY = []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
	}
	return w
}

func twoDigits(n int) string {
	if n < 10 {
		return "0" + strconv.Itoa(n)
	}
	return strconv.Itoa(n)
}

// cpoReportingDate is reporting_date: today, or the last day of a past year.
func cpoReportingDate(fy string, today time.Time) time.Time {
	n, _ := strconv.Atoi(fy)
	last := date(n, time.September, 30)
	if today.Before(last) {
		return today
	}
	return last
}

// cpoOperationalFY is get_operational_fy for a moment (by its UTC day).
func cpoOperationalFY(t time.Time) int {
	u := t.UTC()
	if u.Month() >= time.October {
		return u.Year() + 1
	}
	return u.Year()
}

func fmtSscanWeek(week string, y, wk *int) (int, error) { return fmt.Sscanf(week, "%d-W%d", y, wk) }

// isoWeekStart is the Monday of an ISO week (%G-W%V-1).
func isoWeekStart(year, week int) time.Time {
	jan4 := date(year, time.January, 4)
	monday := jan4.AddDate(0, 0, -((int(jan4.Weekday()) + 6) % 7))
	return monday.AddDate(0, 0, (week-1)*7)
}
