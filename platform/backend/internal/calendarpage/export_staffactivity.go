package calendarpage

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// NationalHolidayCountry is the country the national calendar is kept for
// (public_holidays' national country).
func NationalHolidayCountry() string { return rules.Holidays.NationalCountry }

// PublicHolidayDays is public_holidays_between for [start, end]: each day
// that is a public holiday, as "2006-01-02". It fails for a year the
// national calendar does not cover. For the Staff Activity Log
// (internal/staffactivity), which counts expected working days.
func PublicHolidayDays(ctx context.Context, db schooldirectory.Querier, start, end time.Time) (map[string]bool, error) {
	days, err := newHolidayBook(db).publicBetween(ctx,
		day(start.Year(), start.Month(), start.Day()), day(end.Year(), end.Month(), end.Day()))
	if err != nil {
		return nil, err
	}
	out := make(map[string]bool, len(days))
	for d := range days {
		out[d.Format(time.DateOnly)] = true
	}
	return out, nil
}
