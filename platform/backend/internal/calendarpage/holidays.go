package calendarpage

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// holiday is public_holidays.Holiday: one named day.
type holiday struct {
	date     time.Time
	name     string
	public   bool
	expected bool
	recorded bool
}

// label is Holiday.label: an Eid not yet announced says so.
func (h holiday) label() string {
	if h.expected {
		return h.name + " (expected date)"
	}
	return h.name
}

var notLetters = regexp.MustCompile(`[^a-z]+`)

// eidNamed is public_holidays._eid_named: which Eid a recorded title names,
// however it is spelt, or "".
func eidNamed(title string) string {
	letters := notLetters.ReplaceAllString(casefold(title), "")
	for _, part := range rules.Holidays.FitrSpellings {
		if strings.Contains(letters, part) {
			return rules.Holidays.EidAlFitr
		}
	}
	for _, part := range rules.Holidays.AdhaSpellings {
		if strings.Contains(letters, part) {
			return rules.Holidays.EidAlAdha
		}
	}
	return ""
}

// holidayBook reads the calendar of each year once per page.
type holidayBook struct {
	db    schooldirectory.Querier
	years map[int][]holiday
}

func newHolidayBook(db schooldirectory.Querier) *holidayBook {
	return &holidayBook{db: db, years: map[int][]holiday{}}
}

// recorded is public_holidays._recorded for one year: PublicHoliday rows and
// the active PUBLIC_HOLIDAY blocks of the national country, a day each.
func (b *holidayBook) recorded(ctx context.Context, start, end time.Time) ([]holiday, error) {
	out := []holiday{}
	rows, err := b.db.Query(ctx, `SELECT date, name FROM public_holiday WHERE date BETWEEN $1 AND $2`, start, end)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the recorded holidays: %w", err)
	}
	for rows.Next() {
		var h holiday
		if err := rows.Scan(&h.date, &h.name); err != nil {
			rows.Close()
			return nil, fmt.Errorf("calendarpage: reading the recorded holidays: %w", err)
		}
		h.public, h.recorded = true, true
		out = append(out, h)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("calendarpage: reading the recorded holidays: %w", err)
	}
	rows, err = b.db.Query(ctx, `
SELECT start_date, end_date, title FROM calendar_block
WHERE block_type = $1 AND is_active AND country = $2 AND start_date <= $4 AND end_date >= $3`,
		rules.Holidays.RecordedBlockType, rules.Holidays.NationalCountry, start, end)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the holiday blocks: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var from, to time.Time
		var title string
		if err := rows.Scan(&from, &to, &title); err != nil {
			return nil, fmt.Errorf("calendarpage: reading the holiday blocks: %w", err)
		}
		for day := later(from, start); !day.After(earlier(to, end)); day = day.AddDate(0, 0, 1) {
			out = append(out, holiday{date: day, name: title, public: true, recorded: true})
		}
	}
	return out, rows.Err()
}

// year is public_holidays._year_holidays: the recorded days first on a day
// both sources name, an announced Eid in place of the expected one.
func (b *holidayBook) year(ctx context.Context, year int) ([]holiday, error) {
	if days, ok := b.years[year]; ok {
		return days, nil
	}
	national, ok := rules.Holidays.national[year]
	if !ok {
		return nil, fmt.Errorf("calendarpage: no national calendar for %d", year)
	}
	recorded, err := b.recorded(ctx, day(year, 1, 1), day(year, 12, 31))
	if err != nil {
		return nil, err
	}
	all := mergeYear(national, recorded)
	b.years[year] = all
	return all, nil
}

// between is holidays_between: every named day in [start, end].
func (b *holidayBook) between(ctx context.Context, start, end time.Time) ([]holiday, error) {
	out := []holiday{}
	if start.After(end) {
		return out, nil
	}
	for y := start.Year(); y <= end.Year(); y++ {
		days, err := b.year(ctx, y)
		if err != nil {
			return nil, err
		}
		for _, h := range days {
			if !h.date.Before(start) && !h.date.After(end) {
				out = append(out, h)
			}
		}
	}
	return out, nil
}

// publicBetween is public_holidays_between: the first public holiday of
// each day, by its label.
func (b *holidayBook) publicBetween(ctx context.Context, start, end time.Time) (map[time.Time]string, error) {
	days, err := b.between(ctx, start, end)
	if err != nil {
		return nil, err
	}
	out := map[time.Time]string{}
	for _, h := range days {
		if _, seen := out[h.date]; h.public && !seen {
			out[h.date] = h.label()
		}
	}
	return out, nil
}

func absDays(a, b time.Time) int {
	d := int(a.Sub(b).Hours() / 24)
	if d < 0 {
		return -d
	}
	return d
}

// mergeYear is the body of _year_holidays: the recorded days and the
// national ones they leave, by day, a recorded day first, then by name.
func mergeYear(national, recorded []holiday) []holiday {
	taken := map[time.Time]bool{}
	for _, h := range recorded {
		taken[h.date] = true
	}
	replaced := func(h holiday) bool {
		if !h.expected {
			return false
		}
		for _, r := range recorded {
			if eidNamed(r.name) == h.name && absDays(r.date, h.date) <= rules.Holidays.EidReachDays {
				return true
			}
		}
		return false
	}
	all := append([]holiday{}, recorded...)
	for _, h := range national {
		if !replaced(h) && !(h.public && taken[h.date]) {
			all = append(all, h)
		}
	}
	sort.SliceStable(all, func(i, j int) bool {
		a, c := all[i], all[j]
		if !a.date.Equal(c.date) {
			return a.date.Before(c.date)
		}
		if a.recorded != c.recorded {
			return a.recorded
		}
		return a.name < c.name
	})
	return all
}
