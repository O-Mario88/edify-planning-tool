package targets

import (
	"math"
	"strconv"
	"time"
)

// Days are calendar days at midnight UTC, compared and stepped as dates.

func date(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

// Day is t's calendar day.
func Day(t time.Time) time.Time { return date(t.Year(), t.Month(), t.Day()) }

func fyNumber(fy string) int {
	n, err := strconv.Atoi(fy)
	if err != nil {
		return 0
	}
	return n
}

// FYRange is get_fy_date_range as days: [1 Oct before, 1 Oct of the year).
func FYRange(fy string) (time.Time, time.Time) {
	n := fyNumber(fy)
	return date(n-1, time.October, 1), date(n, time.October, 1)
}

// MonthRange is month m (1 = October) of the year: [its first day, the next
// month's first day).
func MonthRange(fy string, m int) (time.Time, time.Time) {
	start, _ := FYRange(fy)
	s := start.AddDate(0, m-1, 0)
	return s, s.AddDate(0, 1, 0)
}

// QuarterRange is Q1 (October to December) … Q4 of the year.
func QuarterRange(fy, quarter string) (time.Time, time.Time) {
	months := MonthsOfQuarter(quarter)
	s, _ := MonthRange(fy, months[0])
	_, e := MonthRange(fy, months[2])
	return s, e
}

// MonthsOfQuarter is months_of_quarter.
func MonthsOfQuarter(quarter string) []int {
	for i, q := range rules.Quarters {
		if q == quarter {
			return []int{i*3 + 1, i*3 + 2, i*3 + 3}
		}
	}
	return nil
}

// QuarterOfMonth is quarter_of_month.
func QuarterOfMonth(m int) string { return rules.Quarters[(m-1)/3] }

// MonthOfFY is month_of_fy_for: 1..12 when d falls inside the year, else 0.
func MonthOfFY(d time.Time, fy string) int {
	start, end := FYRange(fy)
	if d.Before(start) || !d.Before(end) {
		return 0
	}
	return (d.Year()-start.Year())*12 + int(d.Month()) - int(start.Month()) + 1
}

// MonthLabel is month_label: "November 2026".
func MonthLabel(fy string, m int) string {
	s, _ := MonthRange(fy, m)
	return s.Format("January 2006")
}

// calendar is one person's working days: the year's public holidays and
// their approved leave.
type calendar struct {
	holidays map[string]bool
	leave    map[string]bool
}

// workingDays is working_days: weekdays in [start, end) that are neither a
// public holiday nor one of the person's leave days.
func (c calendar) workingDays(start, end time.Time) int {
	n := 0
	for d := start; d.Before(end); d = d.AddDate(0, 0, 1) {
		key := d.Format(time.DateOnly)
		if wd := d.Weekday(); wd != time.Saturday && wd != time.Sunday && !c.holidays[key] && !c.leave[key] {
			n++
		}
	}
	return n
}

// expectedPace is expected_pace_pct: the share of the period's working days
// already gone at today; 0 before it, 100 after it.
func (c calendar) expectedPace(start, end, today time.Time) int {
	if today.Before(start) {
		return 0
	}
	if !today.Before(end) {
		return 100
	}
	total := c.workingDays(start, end)
	if total == 0 {
		return 100
	}
	elapsed := c.workingDays(start, today.AddDate(0, 0, 1))
	return min(100, int(math.RoundToEven(float64(elapsed)/float64(total)*100)))
}

// WorkingDays is working_days with no person: weekdays in [start, end) that
// are not a public holiday the roster read.
func (r *Roster) WorkingDays(start, end time.Time) int {
	return calendar{holidays: r.holidays}.workingDays(start, end)
}
