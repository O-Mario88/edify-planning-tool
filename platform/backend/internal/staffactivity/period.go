package staffactivity

import (
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// period is services.activity_period: the days a period covers, both
// included, as dates (midnight UTC), with its label.
type period struct {
	key                     string
	on, start, end, elapsed time.Time
	label                   string
	isDefault, isFuture     bool
}

func civil(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func dateOf(t time.Time) time.Time {
	local := t.In(zone)
	return civil(local.Year(), local.Month(), local.Day())
}

// isoDate is date.fromisoformat (Python 3.11+): YYYY-MM-DD, YYYYMMDD and the
// ISO week dates YYYY-Www[-D] and YYYYWww[D]. ok is false where Python raises.
var (
	isoExtended = regexp.MustCompile(`^(\d{4})-(\d{2})-(\d{2})$`)
	isoBasic    = regexp.MustCompile(`^(\d{4})(\d{2})(\d{2})$`)
	// The basic and extended week forms are not mixed.
	isoWeekExtended = regexp.MustCompile(`^(\d{4})-W(\d{2})(?:-(\d))?$`)
	isoWeekBasic    = regexp.MustCompile(`^(\d{4})W(\d{2})(\d)?$`)
)

func isoDate(text string) (time.Time, bool) {
	m := isoExtended.FindStringSubmatch(text)
	if m == nil {
		m = isoBasic.FindStringSubmatch(text)
	}
	if m != nil {
		y, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		d, _ := strconv.Atoi(m[3])
		t := civil(y, time.Month(mo), d)
		if y < 1 || t.Year() != y || int(t.Month()) != mo || t.Day() != d {
			return time.Time{}, false
		}
		return t, true
	}
	w := isoWeekExtended.FindStringSubmatch(text)
	if w == nil {
		w = isoWeekBasic.FindStringSubmatch(text)
	}
	if w == nil {
		return time.Time{}, false
	}
	y, _ := strconv.Atoi(w[1])
	week, _ := strconv.Atoi(w[2])
	day := 1
	if w[3] != "" {
		day, _ = strconv.Atoi(w[3])
	}
	if y < 1 || week < 1 || day < 1 || day > 7 || week > isoWeeks(y) {
		return time.Time{}, false
	}
	jan4 := civil(y, time.January, 4)
	monday := jan4.AddDate(0, 0, -((int(jan4.Weekday()) + 6) % 7))
	return monday.AddDate(0, 0, (week-1)*7+day-1), true
}

// isoWeeks is the number of ISO weeks in a year (52 or 53).
func isoWeeks(y int) int {
	_, w := civil(y, time.December, 28).ISOWeek()
	return w
}

func dayLabel(d time.Time, year bool) string {
	s := fmt.Sprintf("%d %s", d.Day(), d.Format("Jan"))
	if year {
		s += fmt.Sprintf(" %d", d.Year())
	}
	return s
}

func weekday(d time.Time) int { return (int(d.Weekday()) + 6) % 7 } // Monday 0

// operationalFY is apps.core.fy.get_operational_fy for a date.
func operationalFY(d time.Time) int {
	if d.Month() >= time.October {
		return d.Year() + 1
	}
	return d.Year()
}

func quarterOf(d time.Time) (string, time.Month) {
	switch m := d.Month(); {
	case m >= time.October:
		return "Q1", time.October
	case m <= time.March:
		return "Q2", time.January
	case m <= time.June:
		return "Q3", time.April
	default:
		return "Q4", time.July
	}
}

// choosePeriod is presence.presence_period plus activity_period's elapsed
// end: an unknown period is a day, an unreadable date is today.
func choosePeriod(key, on string, today time.Time) period {
	if _, ok := label(rules.Periods, key); !ok {
		key = "day"
	}
	day := today
	if on != "" {
		if d, ok := isoDate(strings.TrimSpace(on)); ok {
			day = d
		}
	}
	p := period{key: key, on: day}
	switch key {
	case "week":
		p.start = day.AddDate(0, 0, -weekday(day))
		p.end = p.start.AddDate(0, 0, 6)
		switch {
		case p.start.Year() != p.end.Year():
			p.label = "week of " + dayLabel(p.start, true) + " – " + dayLabel(p.end, true)
		case p.start.Month() != p.end.Month():
			p.label = "week of " + dayLabel(p.start, false) + " – " + dayLabel(p.end, true)
		default:
			p.label = fmt.Sprintf("week of %d–%s", p.start.Day(), dayLabel(p.end, true))
		}
	case "month":
		p.start = civil(day.Year(), day.Month(), 1)
		p.end = p.start.AddDate(0, 1, -1)
		p.label = p.start.Format("January 2006")
	case "quarter", "fy":
		fy := operationalFY(day)
		var name string
		if key == "quarter" {
			q, month := quarterOf(day)
			year := fy
			if q == "Q1" {
				year = fy - 1
			}
			p.start = civil(year, month, 1)
			p.end = p.start.AddDate(0, 3, -1)
			name = fmt.Sprintf("%s FY%d", q, fy)
		} else {
			p.start = civil(fy-1, time.October, 1)
			p.end = civil(fy, time.September, 30)
			name = fmt.Sprintf("FY%d", fy)
		}
		p.label = fmt.Sprintf("%s (%s – %s)", name, p.start.Format("Jan 2006"), p.end.Format("Jan 2006"))
	default:
		p.start, p.end = day, day
		if day.Equal(today) {
			p.label = "today"
		} else {
			p.label = day.Format("Mon") + " " + dayLabel(day, true)
		}
	}
	p.isDefault = key == "day" && day.Equal(today)
	p.elapsed = p.end
	if today.Before(p.elapsed) {
		p.elapsed = today
	}
	p.isFuture = p.start.After(today)
	return p
}

// bounds is services._bounds: the period's first instant and the instant
// after its last day, in the platform's time zone.
func (p period) bounds() (time.Time, time.Time) {
	at := func(d time.Time) time.Time { return time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, zone) }
	return at(p.start), at(p.end.AddDate(0, 0, 1))
}

// capfirst is Django's capfirst.
func capfirst(s string) string {
	for i, r := range s {
		return string(unicode.ToUpper(r)) + s[i+len(string(r)):]
	}
	return s
}

// minutes is presence.format_minutes: hours and minutes, "<1m" for less than
// a minute of time, "0m" for none.
func minutes(seconds float64) string {
	s := int64(seconds)
	m := s / 60
	if m <= 0 {
		if s > 0 {
			return "<1m"
		}
		return "0m"
	}
	if h := m / 60; h > 0 {
		return fmt.Sprintf("%dh %02dm", h, m%60)
	}
	return fmt.Sprintf("%dm", m)
}

// clock is services._clock: 07:01 today, 28/09 07:01 otherwise.
func clock(at *time.Time, today time.Time) string {
	if at == nil {
		return "—"
	}
	local := at.In(zone)
	if dateOf(*at).Equal(today) {
		return local.Format("15:04")
	}
	return local.Format("02/01 15:04")
}

// pyRound is Python's round() of a float to an integer: half to even.
func pyRound(x float64) int { return int(math.RoundToEven(x)) }

// share is round(part / whole * 100), as the page works it out.
func share(part, whole int64) int {
	return pyRound(float64(part) / float64(whole) * 100)
}

// pyLower is str.lower for the names the page sorts and searches.
func pyLower(s string) string {
	return strings.ToLower(strings.ReplaceAll(s, "İ", "i̇"))
}

// pyTitle is str.title: a letter after a cased letter is lowered, any other
// letter raised.
func pyTitle(s string) string {
	var b strings.Builder
	cased := false
	for _, r := range s {
		switch {
		case unicode.IsLetter(r) && cased:
			b.WriteRune(unicode.ToLower(r))
		case unicode.IsLetter(r):
			b.WriteRune(unicode.ToTitle(r))
		default:
			b.WriteRune(r)
		}
		cased = unicode.IsUpper(r) || unicode.IsLower(r) || unicode.IsTitle(r)
	}
	return b.String()
}

// runes cuts s to n characters, as a Python slice does.
func runes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}
