package ccelead

import (
	"fmt"
	"slices"
	"sort"
	"time"
)

// held is cadence.Held: the part of an engagement the rhythm reads.
type held struct {
	kind, country string
	on            time.Time
	leads         []string
}

// rhythmRow is one row cadence.evaluate writes.
type rhythmRow struct {
	label, expectation, subject, state, note string
	lastHeld, dueBy                          *time.Time
}

// leadInReach is a Programme Lead in the Regional Lead's reach.
type leadInReach struct{ staffID, name, country string }

// opFY is get_operational_fy for a day: the year the October–September year
// ends.
func opFY(d time.Time) int {
	if d.Month() >= time.October {
		return d.Year() + 1
	}
	return d.Year()
}

// quarterRange is get_quarter_date_range(fy, get_quarter_for_date(d)).
func quarterRange(d time.Time) (time.Time, time.Time) {
	m := d.Month()
	start := time.Date(d.Year(), ((m-1)/3)*3+1, 1, 0, 0, 0, 0, time.UTC)
	return start, start.AddDate(0, 3, 0)
}

func latest(dates []time.Time) *time.Time {
	if len(dates) == 0 {
		return nil
	}
	m := dates[0]
	for _, d := range dates[1:] {
		if d.After(m) {
			m = d
		}
	}
	return &m
}

func within(dates []time.Time, start, end time.Time) []time.Time {
	out := []time.Time{}
	for _, d := range dates {
		if !d.Before(start) && d.Before(end) {
			out = append(out, d)
		}
	}
	return out
}

// evaluate is cadence.evaluate: every rhythm row for the lead, worst first.
func evaluate(engagements []held, today time.Time, leads []leadInReach, countries []string, submitted map[string]bool) []rhythmRow {
	c := rules.Cadence
	byKind := map[string][]held{}
	for _, e := range engagements {
		byKind[e.kind] = append(byKind[e.kind], e)
	}
	rows := []rhythmRow{}
	for _, r := range c.Rules {
		entries := byKind[r.Kind]
		row := func(subject, state string, last, due *time.Time, note string) rhythmRow {
			return rhythmRow{label: r.Label, expectation: r.Expectation, subject: subject, state: state, lastHeld: last, dueBy: due, note: note}
		}
		rolling := func(subject string, dates []time.Time) rhythmRow {
			last := latest(dates)
			if last == nil {
				return row(subject, "due_soon", nil, &today, "Not held yet")
			}
			due := last.AddDate(0, 0, *r.EveryDays)
			state := "done"
			switch {
			case due.Before(today):
				state = "overdue"
			case int(due.Sub(today).Hours()/24) <= c.DueSoonDays:
				state = "due_soon"
			}
			return row(subject, state, last, &due, "")
		}
		quarter := func(subject string, dates []time.Time) rhythmRow {
			start, end := quarterRange(today)
			lastDay := end.AddDate(0, 0, -1)
			if in := within(dates, start, end); len(in) > 0 {
				return row(subject, "done", latest(in), &lastDay, "")
			}
			state := "open"
			if int(lastDay.Sub(today).Hours()/24) <= c.QuarterDueSoonDays {
				state = "due_soon"
			}
			return row(subject, state, latest(dates), &lastDay, "This quarter")
		}
		year := func(subject string, dates []time.Time, sent bool) rhythmRow {
			fy := opFY(today)
			start := time.Date(fy-1, time.October, 1, 0, 0, 0, 0, time.UTC)
			end := time.Date(fy, time.October, 1, 0, 0, 0, 0, time.UTC)
			next := fy + 1
			if in := within(dates, start, end); len(in) > 0 {
				return row(subject, "done", latest(in), nil, fmt.Sprintf("Input given for the FY %d budget", next))
			}
			if sent {
				return row(subject, "missed", latest(dates), nil, fmt.Sprintf("The FY %d budget went to the RVP without it", next))
			}
			opens := time.Date(fy, time.Month(c.AnnualWindowOpensMonth), 1, 0, 0, 0, 0, time.UTC)
			if !today.Before(opens) {
				return row(subject, "due_soon", latest(dates), nil, fmt.Sprintf("Before the FY %d budget is submitted", next))
			}
			return row(subject, "open", latest(dates), &opens, "Opens "+opens.Format("2 Jan 2006"))
		}
		switch r.Per {
		case "region":
			dates := []time.Time{}
			for _, e := range entries {
				dates = append(dates, e.on)
			}
			if r.Window == "rolling" {
				rows = append(rows, rolling("Region", dates))
			} else {
				rows = append(rows, quarter("Region", dates))
			}
		case "lead":
			for _, l := range leads {
				dates := []time.Time{}
				for _, e := range entries {
					if slices.Contains(e.leads, l.staffID) {
						dates = append(dates, e.on)
					}
				}
				rows = append(rows, rolling(l.name, dates))
			}
		default:
			for _, country := range countries {
				dates := []time.Time{}
				for _, e := range entries {
					if e.country == country {
						dates = append(dates, e.on)
					}
				}
				if r.Window == "quarter" {
					rows = append(rows, quarter(country, dates))
				} else {
					rows = append(rows, year(country, dates, submitted[country]))
				}
			}
		}
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		if c.StateOrder[a.state] != c.StateOrder[b.state] {
			return c.StateOrder[a.state] < c.StateOrder[b.state]
		}
		if a.label != b.label {
			return a.label < b.label
		}
		return a.subject < b.subject
	})
	return rows
}
