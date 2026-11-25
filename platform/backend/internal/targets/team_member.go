package targets

import (
	"math"
	"strconv"
	"strings"
	"time"
)

// AreaCell is one period of one area in a member's matrix.
type AreaCell struct {
	Cell
	Sub string
}

// AreaRow is one area's periods (area_matrix).
type AreaRow struct {
	Key, Label string
	Weight     int
	Periods    []AreaCell
}

// AreaMonth is one area's month (per_area).
type AreaMonth struct {
	Key, Label               string
	Weight, Target, Achieved int
	Pct                      *int
	Gap                      int
}

// TeamMember is PLTeamTargetsService._member: a supervised person's month,
// quarter and year against their agreed areas, read for the month the page
// asks for and the areas its category keeps.
type TeamMember struct {
	Person                                   Person
	Targets, Achieved                        Series
	MonthPct, QuarterPct                     *int
	MonthAchieved, MonthTarget, Remaining    int
	QuarterAchieved, QuarterTarget, Pace     int
	Status, Tone, DisplayStatus, DisplayTone string
	PerArea                                  []AreaMonth
	Cells                                    []Cell
	Matrix                                   []AreaRow
	MetricAreas                              []Area
}

// pyRound is Python's round to an integer (half to even).
func pyRound(v float64) int { return int(math.RoundToEven(v)) }

// TeamMember is _member for p in month of the roster's year: today's pace
// when the year is the current one (100 otherwise), metric the areas the
// page's category keeps (every agreed area for "overall", and for a
// category the person has no area in).
func (r *Roster) TeamMember(p Person, month int, current bool, today time.Time, metric []Area) TeamMember {
	fy := r.FY
	cal := calendar{holidays: r.holidays, leave: r.leave[p.StaffID]}
	areas := r.areas[p.UserID]
	if len(metric) == 0 {
		// metric_areas or areas: a category the person has no area in
		// reads all their areas.
		metric = areas
	}
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
	out := TeamMember{Person: p, Targets: targets, Achieved: achieved, MetricAreas: metric, Pace: 100}
	if current {
		out.Pace = pace(mStart, mEnd)
	}
	out.MonthPct, out.MonthAchieved, out.MonthTarget = WeightedPct(metric, targets, achieved, []int{month})
	out.Remaining = max(0, out.MonthTarget-out.MonthAchieved)
	q := QuarterOfMonth(month)
	out.QuarterPct, out.QuarterAchieved, out.QuarterTarget = WeightedPct(metric, targets, achieved, MonthsOfQuarter(q))
	out.Status, out.Tone = Status(out.MonthPct, out.Pace, !today.Before(mStart), out.MonthTarget > 0)
	out.DisplayStatus, out.DisplayTone = Display(out.Status, out.Tone)
	for _, a := range areas {
		t, ach := targets[a.Key][month-1], achieved[a.Key][month-1]
		row := AreaMonth{Key: a.Key, Label: a.Label, Weight: a.Weight, Target: t, Achieved: ach, Gap: max(0, t-ach)}
		if t != 0 {
			v := pyRound(float64(ach) / float64(t) * 100)
			row.Pct = &v
		}
		out.PerArea = append(out.PerArea, row)
	}
	type spec struct {
		key, label, summary, sub string
		months                   []int
		start, end               time.Time
	}
	monthLabel := MonthLabel(fy, month)
	first, _, _ := strings.Cut(monthLabel, " ")
	specs := []spec{{"month", "Monthly", first, monthLabel, []int{month}, mStart, mEnd}}
	for _, qq := range rules.Quarters {
		s, e := QuarterRange(fy, qq)
		specs = append(specs, spec{qq, qq, qq, QuarterLabel(fy, qq), MonthsOfQuarter(qq), s, e})
	}
	fs, fe := FYRange(fy)
	specs = append(specs, spec{"fy", fyLabel(fy), "Full year", "Full year", []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}, fs, fe})
	cell := func(key, label string, pct *int, ach, target int, start, end time.Time) Cell {
		st, tn := Display(Status(pct, pace(start, end), !today.Before(start), target > 0))
		c := Cell{Key: key, Label: label, Pct: pct, DisplayPct: pct, Achieved: ach, Target: target, Status: st, Tone: tn}
		if st == "Upcoming" {
			c.DisplayPct = nil
		}
		return c
	}
	for _, s := range specs {
		pct, ach, target := WeightedPct(metric, targets, achieved, s.months)
		out.Cells = append(out.Cells, cell(s.key, s.summary, pct, ach, target, s.start, s.end))
	}
	visible := map[string]bool{}
	for _, a := range metric {
		visible[a.Key] = true
	}
	for _, a := range areas {
		if !visible[a.Key] {
			continue
		}
		row := AreaRow{Key: a.Key, Label: a.Label, Weight: a.Weight}
		for _, s := range specs {
			target, valid := 0, 0
			for _, m := range s.months {
				target += targets[a.Key][m-1]
				valid += achieved[a.Key][m-1]
			}
			var pct *int
			if target != 0 {
				v := pyRound(float64(valid) / float64(target) * 100)
				pct = &v
			}
			row.Periods = append(row.Periods, AreaCell{Cell: cell(s.key, s.label, pct, valid, target, s.start, s.end), Sub: s.sub})
		}
		out.Matrix = append(out.Matrix, row)
	}
	return out
}

// fyLabel is "FY 2025/26".
func fyLabel(fy string) string {
	n, err := strconv.Atoi(fy)
	if err != nil || len(fy) != 4 {
		return "FY " + fy
	}
	return "FY " + strconv.Itoa(n-1) + "/" + fy[2:]
}
