package targets

import (
	"math"
	"time"
)

// Areas are the areas p is measured on this year, in their order.
func (r *Roster) Areas(p Person) []Area { return r.areas[p.UserID] }

// Targets is _targets_from: an area's explicit months where it has any, else
// its annual figure (the priority's, else the target profile's fallback)
// split over the twelve months, the remainder to the early ones.
func (r *Roster) Targets(p Person) Series {
	out := Series{}
	for _, a := range r.areas[p.UserID] {
		if months, ok := r.explicit[p.UserID][a.Key]; ok {
			var s [12]int
			for i, v := range months {
				if v != nil {
					s[i] = *v
				}
			}
			out[a.Key] = s
			continue
		}
		annual := 0
		switch {
		case a.Annual != nil:
			annual = *a.Annual
		case r.profiles[p.StaffID] != nil:
			for _, column := range rules.AnnualFallback[a.Key] {
				annual += r.profiles[p.StaffID][column]
			}
		}
		base, rem := annual/12, annual%12
		var s [12]int
		for m := 1; m <= 12; m++ {
			s[m-1] = base
			if m <= rem {
				s[m-1]++
			}
		}
		out[a.Key] = s
	}
	return out
}

// Achieved is _achievements_from: each area's validated quantity a month.
func (r *Roster) Achieved(p Person) Series {
	out := Series{}
	for _, a := range r.areas[p.UserID] {
		out[a.Key] = r.ledger[p.UserID][a.Key]
	}
	return out
}

// WeightedPct is weighted_period_pct: each area's share over the months,
// averaged by weight over the areas with a target (none: nil); and the
// achieved and target totals.
func WeightedPct(areas []Area, targets, achieved Series, months []int) (*int, int, int) {
	wsum, psum, totA, totT := 0, 0.0, 0, 0
	for _, a := range areas {
		t, ach := 0, 0
		for _, m := range months {
			t += targets[a.Key][m-1]
			ach += achieved[a.Key][m-1]
		}
		totA += ach
		totT += t
		if t > 0 {
			wsum += a.Weight
			psum += (float64(ach) / float64(t) * 100) * float64(a.Weight)
		}
	}
	if wsum == 0 {
		return nil, totA, totT
	}
	pct := int(math.RoundToEven(psum / float64(wsum)))
	return &pct, totA, totT
}

// Cell is one period of a member's matrix (_member's matrix_cells).
type Cell struct {
	Key, Label       string
	Pct, DisplayPct  *int
	Achieved, Target int
	Status, Tone     string
}

// Member is what _member answers for a person in a month of the year.
type Member struct {
	// Status and Tone are the month's pace-aware state (team_status_for).
	Status, Tone string
	// Cells are the month, Q1 to Q4 and the full year.
	Cells []Cell
}

// Member is _member for p: today's month of the year (December's when today
// lies outside it), its pace, and the month, quarter and year cells.
func (r *Roster) Member(p Person, today time.Time) Member {
	fy := r.FY
	month := MonthOfFY(today, fy)
	current := month != 0
	if !current {
		month = 12
	}
	cal := calendar{holidays: r.holidays, leave: r.leave[p.StaffID]}
	areas := r.areas[p.UserID]
	targets, achieved := r.Targets(p), r.Achieved(p)
	paces := map[[2]time.Time]int{}
	pace := func(start, end time.Time) int {
		k := [2]time.Time{start, end}
		if v, ok := paces[k]; ok {
			return v
		}
		paces[k] = cal.expectedPace(start, end, today)
		return paces[k]
	}
	mStart, mEnd := MonthRange(fy, month)
	monthPace := 100
	if current {
		monthPace = pace(mStart, mEnd)
	}
	mPct, _, mT := WeightedPct(areas, targets, achieved, []int{month})
	status, tone := Status(mPct, monthPace, !today.Before(mStart), mT > 0)

	type spec struct {
		key, label string
		months     []int
		start, end time.Time
	}
	label := MonthLabel(fy, month)
	for i, c := range label {
		if c == ' ' {
			label = label[:i]
			break
		}
	}
	specs := []spec{{"month", label, []int{month}, mStart, mEnd}}
	for _, q := range rules.Quarters {
		s, e := QuarterRange(fy, q)
		specs = append(specs, spec{q, q, MonthsOfQuarter(q), s, e})
	}
	fs, fe := FYRange(fy)
	specs = append(specs, spec{"fy", "Full year", []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}, fs, fe})

	out := Member{Status: status, Tone: tone}
	for _, s := range specs {
		pct, ach, target := WeightedPct(areas, targets, achieved, s.months)
		st, tn := Display(Status(pct, pace(s.start, s.end), !today.Before(s.start), target > 0))
		c := Cell{Key: s.key, Label: s.label, Pct: pct, DisplayPct: pct, Achieved: ach, Target: target, Status: st, Tone: tn}
		if st == "Upcoming" {
			c.DisplayPct = nil
		}
		out.Cells = append(out.Cells, c)
	}
	return out
}

// Pace is expected_pace_pct for p: the share of the period's working days
// (neither a public holiday of the year nor one of p's leave days) gone at
// today; 0 before the period, 100 after it.
func (r *Roster) Pace(p Person, start, end, today time.Time) int {
	return calendar{holidays: r.holidays, leave: r.leave[p.StaffID]}.expectedPace(start, end, today)
}

// QuarterLabel is quarter_label: "Oct – Dec".
func QuarterLabel(fy, quarter string) string {
	start, end := QuarterRange(fy, quarter)
	return start.Format("Jan") + " – " + end.AddDate(0, 0, -1).Format("Jan")
}
