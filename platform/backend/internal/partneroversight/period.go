package partneroversight

import (
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// zone is the day date.today() reads (the application's TIME_ZONE).
var zone = mustZone("Africa/Kampala")

func mustZone(name string) *time.Location {
	loc, err := time.LoadLocation(name)
	if err != nil {
		panic(fmt.Sprintf("partneroversight: time zone %s: %v", name, err))
	}
	return loc
}

// period is oversight_views._period_filters for the links that keep their
// meaning (no Export-drawer type, no month pair, no dates): the year, the
// lens in use, and the week, month and quarter each link carries.
type period struct {
	fy, kind, week, quarter string
	month                   int
}

var (
	fourDigitYear = regexp.MustCompile(`^[1-9][0-9]{3}$`)
	isoWeek       = regexp.MustCompile(`^([1-9][0-9]{3})-W([0-9]{2})$`)
)

// readPeriod reads the period the page would. ok is false for a value whose
// reading Go does not copy (a year that is not four digits, a week the
// parser would have to normalise): the existing application answers those.
func readPeriod(q url.Values, now time.Time) (period, bool) {
	fy := strings.TrimSpace(q.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if !fourDigitYear.MatchString(fy) {
		return period{}, false
	}
	year, _ := strconv.Atoi(fy)

	month := 0
	if raw := strings.TrimSpace(q.Get("month")); allDigits(raw) {
		if n, err := strconv.Atoi(raw); err == nil && n >= 1 && n <= 12 {
			month = n
		}
	}
	quarter := strings.ToUpper(strings.TrimSpace(q.Get("quarter")))
	switch quarter {
	case "Q1", "Q2", "Q3", "Q4":
	default:
		quarter = ""
	}

	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	reference := today
	if schooldirectory.OperationalFY(today) != fy {
		reference = time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	}

	week := strings.TrimSpace(q.Get("week"))
	if week == "" {
		y, w := reference.ISOWeek()
		week = fmt.Sprintf("%04d-W%02d", y, w)
	} else if m := isoWeek.FindStringSubmatch(week); m == nil {
		return period{}, false
	} else if n, _ := strconv.Atoi(m[2]); n < 1 || n > 52 {
		return period{}, false
	}

	kind := strings.ToLower(strings.TrimSpace(q.Get("period")))
	switch kind {
	case "week", "month", "quarter", "fy":
	default:
		switch {
		case month != 0:
			kind = "month"
		case quarter != "":
			kind = "quarter"
		default:
			kind = "fy"
		}
	}
	if month == 0 {
		month = int(reference.Month())
	}
	if quarter == "" {
		quarter = quarterOf(reference)
	}
	return period{fy: fy, kind: kind, week: week, month: month, quarter: quarter}, true
}

// quarterOf is get_quarter_for_date: the financial quarter, October first.
func quarterOf(d time.Time) string {
	switch m := d.Month(); {
	case m >= time.October:
		return "Q1"
	case m <= time.March:
		return "Q2"
	case m <= time.June:
		return "Q3"
	default:
		return "Q4"
	}
}

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}
