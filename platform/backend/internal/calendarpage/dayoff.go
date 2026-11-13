package calendarpage

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The day-off marks (apps.activities.day_off): planned work still waiting
// for its day that runs on a public holiday, or on a day its responsible
// staff member is on approved leave.

type dayOff struct {
	day     time.Time
	holiday bool
	// name is the holiday, or the person on leave; cover who covers them.
	name, cover string
}

// sentence is DayOff.sentence.
func (d dayOff) sentence() string {
	if d.holiday {
		return shortDay(d.day) + " is a public holiday (" + d.name + ")."
	}
	text := d.name + " is on leave on " + shortDay(d.day) + "."
	if d.cover != "" {
		text += " " + d.cover + " is covering."
	}
	return text
}

type dayOffMark struct{ days []dayOff }

// label is DayOffMark.label.
func (m dayOffMark) label() string {
	holiday, onLeave := false, false
	for _, d := range m.days {
		if d.holiday {
			holiday = true
		} else {
			onLeave = true
		}
	}
	switch {
	case holiday && !onLeave:
		return "Public holiday"
	case onLeave && !holiday:
		return "On leave"
	}
	return "Holiday and leave"
}

// why is DayOffMark.why.
func (m dayOffMark) why() string {
	parts := make([]string, 0, len(m.days))
	for _, d := range m.days {
		parts = append(parts, d.sentence())
	}
	return strings.Join(parts, " ")
}

// spell is one approved leave.
type spell struct {
	start, end time.Time
	cover      string
}

// span is the days an activity runs on.
type span struct{ start, end time.Time }

// leaveSpells is day_off._leave_by_owner: owner id (either id space) ->
// the person's name and their approved leave in [first, last].
func leaveSpells(ctx context.Context, db schooldirectory.Querier, owners []string, first, last time.Time) (map[string]string, map[string][]spell, error) {
	names, spells := map[string]string{}, map[string][]spell{}
	if len(owners) == 0 {
		return names, spells, nil
	}
	rows, err := db.Query(ctx, `
SELECT sp.id, sp.user_id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, owners)
	if err != nil {
		return nil, nil, fmt.Errorf("calendarpage: reading the responsible staff: %w", err)
	}
	type profile struct {
		id, userID string
		name       *string
	}
	profiles := []profile{}
	ids := []string{}
	for rows.Next() {
		var p profile
		if err := rows.Scan(&p.id, &p.userID, &p.name); err != nil {
			rows.Close()
			return nil, nil, fmt.Errorf("calendarpage: reading the responsible staff: %w", err)
		}
		profiles = append(profiles, p)
		ids = append(ids, p.id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("calendarpage: reading the responsible staff: %w", err)
	}
	if len(profiles) == 0 {
		return names, spells, nil
	}
	rows, err = db.Query(ctx, `
SELECT l.staff_id, l.start_date, l.end_date, COALESCE(cu.name, '')
FROM leave l
LEFT JOIN staff_profile cs ON cs.id = l.covering_staff_id
LEFT JOIN "user" cu ON cu.id = cs.user_id
WHERE l.staff_id = ANY($1) AND l.status = 'approved' AND l.start_date <= $2 AND l.end_date >= $3`,
		ids, last.Format(time.DateOnly), first.Format(time.DateOnly))
	if err != nil {
		return nil, nil, fmt.Errorf("calendarpage: reading approved leave: %w", err)
	}
	byStaff := map[string][]spell{}
	for rows.Next() {
		var staff, from, to, cover string
		if err := rows.Scan(&staff, &from, &to, &cover); err != nil {
			rows.Close()
			return nil, nil, fmt.Errorf("calendarpage: reading approved leave: %w", err)
		}
		start, okStart := isoDate(from)
		end, okEnd := isoDate(to)
		if !okStart || !okEnd {
			continue
		}
		byStaff[staff] = append(byStaff[staff], spell{start: start, end: end, cover: cover})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("calendarpage: reading approved leave: %w", err)
	}
	for _, p := range profiles {
		s, ok := byStaff[p.id]
		if !ok {
			continue
		}
		name := "The responsible staff member"
		if p.name != nil && *p.name != "" {
			name = *p.name
		}
		for _, id := range []string{p.id, p.userID} {
			names[id], spells[id] = name, s
		}
	}
	return names, spells, nil
}

// dayOffMarks is day_off.day_off_marks over the month's rows, with the
// calendar's own spans.
func dayOffMarks(ctx context.Context, db schooldirectory.Querier, book *holidayBook, rows []*activity, spans map[string]span) (map[string]dayOffMark, error) {
	waiting := []*activity{}
	var first, last time.Time
	owners := []string{}
	for _, a := range rows {
		s, ok := spans[a.id]
		if !in(rules.AwaitingDelivery, a.status) || !ok {
			continue
		}
		if len(waiting) == 0 || s.start.Before(first) {
			first = s.start
		}
		if len(waiting) == 0 || s.end.After(last) {
			last = s.end
		}
		waiting = append(waiting, a)
		if a.staffID != "" && !in(owners, a.staffID) {
			owners = append(owners, a.staffID)
		}
	}
	marks := map[string]dayOffMark{}
	if len(waiting) == 0 {
		return marks, nil
	}
	holidays, err := book.publicBetween(ctx, first, last)
	if err != nil {
		return nil, err
	}
	names, spells, err := leaveSpells(ctx, db, owners, first, last)
	if err != nil {
		return nil, err
	}
	for _, a := range waiting {
		s := spans[a.id]
		days := []dayOff{}
		for d := s.start; !d.After(s.end); d = d.AddDate(0, 0, 1) {
			if name, ok := holidays[d]; ok {
				days = append(days, dayOff{day: d, holiday: true, name: name})
			}
			for _, sp := range spells[a.staffID] {
				if !d.Before(sp.start) && !d.After(sp.end) {
					days = append(days, dayOff{day: d, name: names[a.staffID], cover: sp.cover})
					break
				}
			}
		}
		if len(days) > 0 {
			marks[a.id] = dayOffMark{days: days}
		}
	}
	return marks, nil
}

// isoDate is date.fromisoformat of the YYYY-MM-DD text leave is stored as.
func isoDate(text string) (time.Time, bool) {
	t, err := time.Parse(time.DateOnly, text)
	return t, err == nil
}
