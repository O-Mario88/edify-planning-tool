package teamperformance

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// The period kinds (periods.KINDS).
const (
	kindWeek    = "week"
	kindMonth   = "month"
	kindQuarter = "quarter"
	kindYear    = "year"
)

// day is a calendar date, held as midnight UTC.
type day = time.Time

func dateOf(y int, m time.Month, d int) day { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func addDays(d day, n int) day { return d.AddDate(0, 0, n) }

// weekday is Python's date.weekday(): Monday 0.
func weekday(d day) int { return (int(d.Weekday()) + 6) % 7 }

func minDay(a, b day) day {
	if a.Before(b) {
		return a
	}
	return b
}

func maxDay(a, b day) day {
	if a.After(b) {
		return a
	}
	return b
}

// window is [start, end).
type window struct{ start, end day }

// period is periods.ReportPeriod: one chosen week, month, quarter or year.
type period struct {
	fy      string
	kind    string
	month   int // of the FY, 1 = October
	quarter int
	week    day // the chosen week's Monday
	today   day
}

// pyInt is periods._int: an int in [low, high], else not one.
func pyInt(value string, low, high int) (int, bool) {
	n, ok := parsePyInt(value)
	if !ok || n < low || n > high {
		return 0, false
	}
	return n, true
}

// parsePyInt is Python's int(str): surrounding whitespace, a sign, digits and
// single underscores between digits.
func parsePyInt(value string) (int, bool) {
	text := strings.TrimSpace(value)
	if text == "" {
		return 0, false
	}
	sign := ""
	if text[0] == '+' || text[0] == '-' {
		sign, text = text[:1], text[1:]
	}
	if text == "" || text[0] == '_' || text[len(text)-1] == '_' || strings.Contains(text, "__") {
		return 0, false
	}
	digits := strings.ReplaceAll(text, "_", "")
	for _, r := range digits {
		if r < '0' || r > '9' {
			return 0, false
		}
	}
	n, err := strconv.Atoi(sign + digits)
	if err != nil {
		return 0, false
	}
	return n, true
}

// pyDate is date.fromisoformat: YYYY-MM-DD, YYYYMMDD and the ISO week forms
// YYYY-Www, YYYY-Www-D, YYYYWww and YYYYWwwD.
func pyDate(value string) (day, bool) {
	for _, layout := range []string{"2006-01-02", "20060102"} {
		if len(value) != len(layout) {
			continue
		}
		if t, err := time.Parse(layout, value); err == nil {
			return dateOf(t.Year(), t.Month(), t.Day()), true
		}
	}
	return isoWeekDate(value)
}

var isoWeek = regexp.MustCompile(`^(\d{4})(?:-W(\d{2})(?:-(\d))?|W(\d{2})(\d)?)$`)

func isoWeekDate(value string) (day, bool) {
	m := isoWeek.FindStringSubmatch(value)
	if m == nil {
		return day{}, false
	}
	year, _ := strconv.Atoi(m[1])
	weekText, dayText := m[2], m[3]
	if weekText == "" {
		weekText, dayText = m[4], m[5]
	}
	week, _ := strconv.Atoi(weekText)
	wd := 1
	if dayText != "" {
		wd, _ = strconv.Atoi(dayText)
	}
	if year < 1 || week < 1 || week > 53 || wd < 1 || wd > 7 {
		return day{}, false
	}
	jan4 := dateOf(year, time.January, 4)
	first := addDays(jan4, -weekday(jan4))
	if week == 53 {
		// Only a year whose last ISO week is the 53rd has one.
		_, last := dateOf(year, time.December, 28).ISOWeek()
		if last != 53 {
			return day{}, false
		}
	}
	return addDays(first, (week-1)*7+wd-1), true
}

func resolvePeriod(fy, month, kind, quarter, week string, today day) period {
	current := operationalFYOf(today)
	// A year from a link is read only when it is one; str(fy) keeps its text.
	if _, ok := pyInt(fy, 2000, 2999); !ok {
		fy = current
	}
	return resolveWith(fy, current, month, kind, quarter, week, today)
}

func resolveWith(fy, current, month, kind, quarter, week string, today day) period {
	var anchor day
	fyN, _ := parsePyInt(fy)
	curN, _ := strconv.Atoi(current)
	switch {
	case fy == current:
		anchor = today
	case fyN < curN:
		anchor = dateOf(fyN, time.September, 30)
	default:
		anchor = dateOf(fyN-1, time.October, 1)
	}
	defaultMonth := ((int(anchor.Month())-10)%12+12)%12 + 1
	m, ok := pyInt(month, 1, 12)
	if !ok {
		m = defaultMonth
	}
	q, ok := pyInt(quarter, 1, 4)
	if !ok {
		q = (m-1)/3 + 1
	}
	monday, ok := pyDate(week)
	if !ok {
		monday = anchor
	}
	monday = addDays(monday, -weekday(monday))
	switch kind {
	case kindWeek, kindMonth, kindQuarter, kindYear:
	default:
		kind = kindMonth
	}
	return period{fy: fy, kind: kind, month: m, quarter: q, week: monday, today: today}
}

// operationalFYOf is get_operational_fy of a calendar day.
func operationalFYOf(d day) string {
	if d.Month() >= time.October {
		return strconv.Itoa(d.Year() + 1)
	}
	return strconv.Itoa(d.Year())
}

// monthWindow is get_month_date_range: month 1 is October of fy-1.
func monthWindowOf(fy string, month int) window {
	n, _ := parsePyInt(fy)
	start := dateOf(n-1, time.October, 1).AddDate(0, month-1, 0)
	return window{start, start.AddDate(0, 1, 0)}
}

func (p period) monthWindow(month int) window { return monthWindowOf(p.fy, month) }

func (p period) fyStart() day { return p.monthWindow(1).start }
func (p period) fyEnd() day   { return p.monthWindow(12).end }

func (p period) clip(d day) day { return minDay(maxDay(d, p.fyStart()), p.fyEnd()) }

func (p period) span() window {
	switch p.kind {
	case kindWeek:
		return window{p.clip(p.week), p.clip(addDays(p.week, 7))}
	case kindQuarter:
		return window{p.monthWindow(p.quarter*3 - 2).start, p.monthWindow(p.quarter * 3).end}
	case kindYear:
		return window{p.fyStart(), p.fyEnd()}
	}
	return p.monthWindow(p.month)
}

func (p period) toDate() window {
	s := p.span()
	end := minDay(s.end, addDays(p.today, 1))
	return window{p.fyStart(), maxDay(end, s.start)}
}

func (p period) before() window { return window{p.fyStart(), p.span().start} }

func (p period) months() []int {
	switch p.kind {
	case kindQuarter:
		return []int{p.quarter*3 - 2, p.quarter*3 - 1, p.quarter * 3}
	case kindYear:
		return []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
	case kindMonth:
		return []int{p.month}
	}
	return nil
}

func (p period) lastMonth() int {
	switch p.kind {
	case kindQuarter:
		return p.quarter * 3
	case kindMonth:
		return p.month
	}
	last := addDays(p.span().end, -1)
	return ((int(last.Month())-10)%12+12)%12 + 1
}

func (p period) through(month int) window { return window{p.fyStart(), p.monthWindow(month).end} }

func (p period) quarterStarted(q int) bool { return !p.monthWindow(q*3 - 2).start.After(p.today) }

func (p period) monthSpan() window { return p.monthWindow(p.month) }

func (p period) monthToDate() window {
	mw := p.monthWindow(p.month)
	end := minDay(mw.end, addDays(p.today, 1))
	return window{p.fyStart(), maxDay(end, mw.start)}
}

func (p period) monthBefore() window { return window{p.fyStart(), p.monthWindow(p.month).start} }

func (p period) now() window { return window{p.fyStart(), minDay(p.fyEnd(), addDays(p.today, 1))} }

func (p period) label() string {
	s := p.span()
	last := addDays(s.end, -1)
	switch p.kind {
	case kindWeek:
		return fmt.Sprintf("Week of %d %s", s.start.Day(), s.start.Format("Jan 2006"))
	case kindQuarter:
		return fmt.Sprintf("Q%d FY%s (%s–%s)", p.quarter, p.fy, s.start.Format("Jan"), last.Format("Jan 2006"))
	case kindYear:
		return fmt.Sprintf("FY%s (%s–%s)", p.fy, s.start.Format("Jan 2006"), last.Format("Jan 2006"))
	}
	return s.start.Format("January 2006")
}

func (p period) previousLabel() string {
	return map[string]string{kindWeek: "last week", kindMonth: "last month", kindQuarter: "last quarter", kindYear: "last year"}[p.kind]
}

func (p period) monthLabel() string { return p.monthWindow(p.month).start.Format("January 2006") }

func (p period) monthOptions() [][2]string {
	out := [][2]string{}
	for m := 1; m <= 12; m++ {
		out = append(out, [2]string{strconv.Itoa(m), p.monthWindow(m).start.Format("January 2006")})
	}
	return out
}

func (p period) quarterOptions() [][2]string {
	out := [][2]string{}
	for q := 1; q <= 4; q++ {
		start := p.monthWindow(q*3 - 2).start
		last := addDays(p.monthWindow(q*3).end, -1)
		out = append(out, [2]string{strconv.Itoa(q), fmt.Sprintf("Q%d (%s–%s)", q, start.Format("Jan"), last.Format("Jan 2006"))})
	}
	return out
}

func (p period) weekOptions() [][2]string {
	first := addDays(p.fyStart(), -weekday(p.fyStart()))
	last := minDay(p.today, addDays(p.fyEnd(), -1))
	weeks := [][2]string{}
	for monday := first; !monday.After(last); monday = addDays(monday, 7) {
		weeks = append(weeks, [2]string{monday.Format("2006-01-02"), fmt.Sprintf("Week of %d %s", monday.Day(), monday.Format("Jan 2006"))})
	}
	for i, j := 0, len(weeks)-1; i < j; i, j = i+1, j-1 {
		weeks[i], weeks[j] = weeks[j], weeks[i]
	}
	return weeks
}
