package workplan

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// dayOffMark is apps.activities.day_off.DayOffMark as a row shows it: the
// kinds of day off the activity runs on.
type dayOffMark struct{ holiday, leave bool }

// label is DayOffMark.label.
func (m dayOffMark) label() string {
	switch {
	case m.holiday && !m.leave:
		return "Public holiday"
	case m.leave && !m.holiday:
		return "On leave"
	}
	return "Holiday and leave"
}

// activitySpan is day_off.activity_span: the days an activity runs on.
func activitySpan(a *activity) (time.Time, time.Time, bool) {
	start := a.planned
	if start == nil {
		start = a.scheduled
	}
	if start == nil {
		return time.Time{}, time.Time{}, false
	}
	end := *start
	if a.endDate != nil && a.endDate.After(*start) {
		end = *a.endDate
	}
	return *start, end, true
}

type spell struct{ start, end time.Time }

// dayOffMarks is day_off.day_off_marks: the activities still waiting for
// their day that run on a public holiday, or on a day their responsible
// staff member is on approved leave.
func dayOffMarks(ctx context.Context, db schooldirectory.Querier, acts []*activity) (map[string]dayOffMark, error) {
	type waiting struct {
		a          *activity
		start, end time.Time
	}
	list := []waiting{}
	for _, a := range acts {
		if !in(rules.DayOff.AwaitingDelivery, a.status) {
			continue
		}
		if start, end, ok := activitySpan(a); ok {
			list = append(list, waiting{a, start, end})
		}
	}
	out := map[string]dayOffMark{}
	if len(list) == 0 {
		return out, nil
	}
	first, last := list[0].start, list[0].end
	owners := []string{}
	for _, w := range list {
		if w.start.Before(first) {
			first = w.start
		}
		if w.end.After(last) {
			last = w.end
		}
		if id := str(w.a.staffID); id != "" && !in(owners, id) {
			owners = append(owners, id)
		}
	}
	holidays, err := publicHolidaysBetween(ctx, db, first, last)
	if err != nil {
		return nil, err
	}
	leave, err := leaveByOwner(ctx, db, owners, first, last)
	if err != nil {
		return nil, err
	}
	for _, w := range list {
		var m dayOffMark
		spells := leave[str(w.a.staffID)]
		for day := w.start; !day.After(w.end); day = day.AddDate(0, 0, 1) {
			if holidays[day] {
				m.holiday = true
			}
			for _, sp := range spells {
				if !day.Before(sp.start) && !day.After(sp.end) {
					m.leave = true
					break
				}
			}
		}
		if m.holiday || m.leave {
			out[w.a.id] = m
		}
	}
	return out, nil
}

// leaveByOwner is day_off._leave_by_owner: each owner id's (staff profile
// or account) approved leave touching [first, last]. A spell whose dates do
// not read as dates is skipped, as the existing code skips it.
func leaveByOwner(ctx context.Context, db schooldirectory.Querier, owners []string, first, last time.Time) (map[string][]spell, error) {
	out := map[string][]spell{}
	if len(owners) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT sp.id, sp.user_id FROM staff_profile sp
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, owners)
	if err != nil {
		return nil, fmt.Errorf("workplan: leave owners: %w", err)
	}
	type profile struct {
		id   string
		user *string
	}
	profiles := []profile{}
	ids := []string{}
	for rows.Next() {
		var p profile
		if err := rows.Scan(&p.id, &p.user); err != nil {
			rows.Close()
			return nil, err
		}
		profiles = append(profiles, p)
		ids = append(ids, p.id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(profiles) == 0 {
		return out, nil
	}
	rows, err = db.Query(ctx, `SELECT staff_id, start_date, end_date FROM leave
WHERE staff_id = ANY($1) AND status = 'approved' AND start_date <= $2 AND end_date >= $3`,
		ids, last.Format(time.DateOnly), first.Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("workplan: leave: %w", err)
	}
	spells := map[string][]spell{}
	for rows.Next() {
		var staff, start, end string
		if err := rows.Scan(&staff, &start, &end); err != nil {
			rows.Close()
			return nil, err
		}
		s, err1 := pyDate(start)
		e, err2 := pyDate(end)
		if err1 != nil || err2 != nil {
			continue
		}
		spells[staff] = append(spells[staff], spell{s, e})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for _, p := range profiles {
		if sp, ok := spells[p.id]; ok {
			out[p.id] = sp
			out[str(p.user)] = sp
		}
	}
	delete(out, "")
	return out, nil
}

// pyDate is date.fromisoformat for the plain YYYY-MM-DD form leave stores.
func pyDate(s string) (time.Time, error) {
	return time.Parse(time.DateOnly, s)
}

// publicHolidaysBetween is public_holidays.public_holidays_between: the days
// in [start, end] that are public holidays, the national calendar's and the
// ones recorded under Holidays & Blackouts, a recorded Eid replacing the
// expected one near it.
func publicHolidaysBetween(ctx context.Context, db schooldirectory.Querier, start, end time.Time) (map[time.Time]bool, error) {
	out := map[time.Time]bool{}
	for year := start.Year(); year <= end.Year(); year++ {
		days, err := yearHolidays(ctx, db, year)
		if err != nil {
			return nil, err
		}
		for _, d := range days {
			if !d.Before(start) && !d.After(end) {
				out[d] = true
			}
		}
	}
	return out, nil
}

// yearHolidays is _year_holidays' public days for one calendar year.
func yearHolidays(ctx context.Context, db schooldirectory.Querier, year int) ([]time.Time, error) {
	r := rules.DayOff
	if year < r.HolidayYears[0] || year > r.HolidayYears[1] {
		return nil, fmt.Errorf("workplan: the national holiday calendar is not written out for %d", year)
	}
	first := time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
	last := time.Date(year, 12, 31, 0, 0, 0, 0, time.UTC)
	type recorded struct {
		day  time.Time
		name string
	}
	rec := []recorded{}
	rows, err := db.Query(ctx, `SELECT date, name FROM public_holiday WHERE date BETWEEN $1 AND $2`, first, last)
	if err != nil {
		return nil, fmt.Errorf("workplan: recorded holidays: %w", err)
	}
	for rows.Next() {
		var x recorded
		if err := rows.Scan(&x.day, &x.name); err != nil {
			rows.Close()
			return nil, err
		}
		rec = append(rec, x)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(ctx, `SELECT start_date, end_date, title FROM calendar_block
WHERE block_type = 'PUBLIC_HOLIDAY' AND is_active AND country = $1 AND start_date <= $2 AND end_date >= $3`,
		r.NationalCountry, last, first)
	if err != nil {
		return nil, fmt.Errorf("workplan: holiday blocks: %w", err)
	}
	for rows.Next() {
		var s, e time.Time
		var title string
		if err := rows.Scan(&s, &e, &title); err != nil {
			rows.Close()
			return nil, err
		}
		if s.Before(first) {
			s = first
		}
		if e.After(last) {
			e = last
		}
		for d := s; !d.After(e); d = d.AddDate(0, 0, 1) {
			rec = append(rec, recorded{d, title})
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	taken := map[time.Time]bool{}
	days := []time.Time{}
	for _, x := range rec {
		taken[x.day] = true
		days = append(days, x.day)
	}
	for _, h := range r.Holidays {
		if h.day.Year() != year || taken[h.day] {
			continue
		}
		replaced := false
		if h.Expected {
			for _, x := range rec {
				gap := x.day.Sub(h.day).Hours() / 24
				if eidNamed(x.name) == h.Name && gap <= float64(r.EidReachDays) && gap >= -float64(r.EidReachDays) {
					replaced = true
				}
			}
		}
		if !replaced {
			days = append(days, h.day)
		}
	}
	sort.Slice(days, func(i, j int) bool { return days[i].Before(days[j]) })
	return days, nil
}

// eidNamed is _eid_named: which Eid a recorded title names, however spelt.
func eidNamed(title string) string {
	letters := strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' {
			return r
		}
		return -1
	}, strings.Map(unicode.ToLower, title))
	if strings.Contains(letters, "fitr") {
		return rules.DayOff.EidAlFitr
	}
	for _, part := range []string{"adha", "adhuha", "azha"} {
		if strings.Contains(letters, part) {
			return rules.DayOff.EidAlAdha
		}
	}
	return ""
}
