package teamtargets

import (
	"context"
	"fmt"
	"sort"
	"strconv"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// signal is one "What needs attention" figure.
type signal struct {
	label, sub, action, drill, tone string
	count                           int
}

func toneOf(bad bool, badTone string) string {
	if bad {
		return badTone
	}
	return "success"
}

// attention is the five operational signals.
func (d *data) attention(ctx context.Context, db schooldirectory.Querier, c core) ([]signal, error) {
	tt, ta := d.t.series(false), d.t.series(true)
	m := d.month - 1
	ssaT, ssaA := tt["ssa_completed"][m], ta["ssa_completed"][m]
	visitT, visitA := tt["school_visits"][m], ta["school_visits"][m]
	scheduled, pending := 0, 0
	if ids := d.t.ids(); len(ids) > 0 {
		if err := db.QueryRow(ctx, `SELECT count(*) FROM activity WHERE responsible_staff_id = ANY($1) AND fy = $2
			AND deleted_at IS NULL AND planned_date >= $3 AND planned_date < $4 AND ssa_collection_expected
			AND status NOT IN ('cancelled', 'rejected')`, ids, d.fy, d.start, d.end).Scan(&scheduled); err != nil {
			return nil, fmt.Errorf("teamtargets: the SSAs scheduled: %w", err)
		}
		if err := db.QueryRow(ctx, `SELECT count(*) FROM ssa_record WHERE collected_by_user_id = ANY($1) AND deleted_at IS NULL
			AND date_of_ssa >= $2 AND date_of_ssa < $3 AND verification_status IS DISTINCT FROM 'confirmed'`, ids, d.start, d.end).
			Scan(&pending); err != nil {
			return nil, fmt.Errorf("teamtargets: the SSAs awaiting IA: %w", err)
		}
	}
	behind := d.t.where("Slightly Behind", "High Risk", "Critical")
	critical := d.t.where("Critical")
	n := strconv.Itoa(len(d.t.rows))
	return []signal{
		{"Staff Behind Target", "of " + n + " supervised staff", "View Staff", "staff", toneOf(len(behind) > 0, "danger"), len(behind)},
		{"Staff at Critical Risk", "below critical threshold", "View Staff", "high_risk", toneOf(len(critical) > 0, "danger"), len(critical)},
		{"SSA Target Gap", strconv.Itoa(scheduled) + " scheduled · " + strconv.Itoa(pending) + " awaiting IA", "View Details",
			"area:ssa_completed", toneOf(ssaT-ssaA > 0, "warning"), max(0, ssaT-ssaA)},
		{"Valid Visit Gap", strconv.Itoa(visitA) + " valid of " + strconv.Itoa(visitT) + " target", "View Details",
			"area:school_visits", toneOf(visitT-visitA > 0, "warning"), max(0, visitT-visitA)},
		{"Core School Target Gap", "of " + strconv.Itoa(c.total) + " core packages", "View Schools", "core",
			toneOf(c.total-c.onTrack != 0, "warning"), c.total - c.onTrack},
	}, nil
}

// progress is one "Priority progress" row: the team's month in an area.
type progress struct {
	key, label, status, tone string
	achieved, target         int
	pct                      *int
}

func (d *data) keyProgress() []progress {
	tt, ta := d.t.series(false), d.t.series(true)
	pace := 100
	if d.current {
		pace = d.roster.Pace(targets.Person{}, d.start, d.end, d.today)
	}
	out := []progress{}
	for _, a := range d.t.metricAreas {
		t, ach := tt[a.Key][d.month-1], ta[a.Key][d.month-1]
		var pct *int
		if t != 0 {
			v := pyRound(float64(ach) / float64(t) * 100)
			pct = &v
		}
		status, tone := targets.Status(pct, pace, !d.today.Before(d.start), t > 0)
		out = append(out, progress{a.Key, a.Label, status, tone, ach, t, pct})
	}
	return out
}

// district is one "Districts most behind" row.
type district struct {
	name                string
	staff, schools, pct int
}

func (d *data) districtsBehind() []district {
	type acc struct {
		pcts           []int
		staff, schools int
	}
	by := map[string]*acc{}
	order := []string{}
	for _, r := range d.t.rows {
		for _, name := range r.districts {
			a := by[name]
			if a == nil {
				a = &acc{}
				by[name] = a
				order = append(order, name)
			}
			v := 0
			if r.MonthPct != nil {
				v = *r.MonthPct
			}
			a.pcts = append(a.pcts, v)
			a.staff++
		}
	}
	seen := map[string]bool{}
	for _, schools := range d.port.of {
		for _, s := range schools {
			if seen[s.id] {
				continue
			}
			seen[s.id] = true
			if a := by[s.district]; s.district != "" && a != nil {
				a.schools++
			}
		}
	}
	out := []district{}
	for _, name := range order {
		a := by[name]
		sum := 0
		for _, p := range a.pcts {
			sum += p
		}
		out = append(out, district{name, a.staff, a.schools, pyRound(float64(sum) / float64(len(a.pcts)))})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].pct < out[j].pct })
	if len(out) > 6 {
		out = out[:6]
	}
	return out
}
