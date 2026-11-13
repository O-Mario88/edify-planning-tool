package calendarpage

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The day-off marks (apps.activities.day_off.day_off_marks) for My Plan,
// which reads them for its own rows (internal/myplan).

// DayOffWork is one activity the marks are asked of: its id, status,
// responsible staff id and the days it runs on (activity_span).
type DayOffWork struct {
	ID, Status, StaffID string
	Start, End          time.Time
}

// DayOffMark is one activity's mark in the words My Plan shows.
type DayOffMark struct {
	// Label is DayOffMark.label, Summary .summary, Why .why, Advice .advice;
	// First is the first day off (the card's order).
	Label, Summary, Why, Advice string
	First                       time.Time
}

// DayOffMarks is day_off_marks over work: only work still waiting for its
// day is marked. ok is false when a day falls in a year the national
// calendar does not hold (the caller passes the page on).
func DayOffMarks(ctx context.Context, db schooldirectory.Querier, work []DayOffWork) (map[string]DayOffMark, bool, error) {
	rows := make([]*activity, 0, len(work))
	spans := map[string]span{}
	for _, w := range work {
		if !in(rules.AwaitingDelivery, w.Status) {
			continue
		}
		for y := w.Start.Year(); y <= w.End.Year(); y++ {
			if _, known := rules.Holidays.national[y]; !known {
				return nil, false, nil
			}
		}
		rows = append(rows, &activity{id: w.ID, status: w.Status, staffID: w.StaffID})
		spans[w.ID] = span{start: w.Start, end: w.End}
	}
	marks, err := dayOffMarks(ctx, db, newHolidayBook(db), rows, spans)
	if err != nil {
		return nil, false, err
	}
	out := make(map[string]DayOffMark, len(marks))
	for id, m := range marks {
		summary := shortDay(m.days[0].day) + " · " + kindWord(m.days[0])
		if more := len(m.days) - 1; more > 0 {
			summary += " +" + itoa(more) + " more"
		}
		why := m.why()
		out[id] = DayOffMark{Label: m.label(), Summary: summary, Why: why, Advice: why + " Reschedule this activity.", First: m.days[0].day}
	}
	return out, true, nil
}

// kindWord is DayOff.short's second half.
func kindWord(d dayOff) string {
	if d.holiday {
		return "Public holiday"
	}
	return "On leave"
}
