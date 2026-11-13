package calendarpage

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Holiday is one public holiday as another page lists it.
type Holiday struct {
	Date  time.Time
	Label string
	// Recorded is a day entered on the platform rather than the national
	// calendar's own.
	Recorded bool
}

// Upcoming is public_holidays.upcoming_public_holidays(today, limit=limit):
// the public holidays from today to a year and a day ahead, one a day,
// soonest first, the national calendar merged with the recorded days, for
// Leave Policies.
func Upcoming(ctx context.Context, db schooldirectory.Querier, today time.Time, limit int) ([]Holiday, error) {
	days, err := newHolidayBook(db).between(ctx, today, today.AddDate(0, 0, 366))
	if err != nil {
		return nil, err
	}
	seen := map[time.Time]bool{}
	out := []Holiday{}
	for _, h := range days {
		if h.public && !seen[h.date] {
			seen[h.date] = true
			out = append(out, Holiday{Date: h.date, Label: h.label(), Recorded: h.recorded})
		}
	}
	return out[:min(limit, len(out))], nil
}
