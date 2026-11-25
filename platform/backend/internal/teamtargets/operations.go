package teamtargets

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// ids are every id the team's work is recorded under (_user_ids: the user
// and their People record).
func (t team) ids() []string {
	out := []string{}
	for _, r := range t.rows {
		out = append(out, r.member.UserID)
		if r.member.StaffID != "" {
			out = append(out, r.member.StaffID)
		}
	}
	return out
}

// sfCompliance is the SF ID compliance figures: of the team's completed
// staff work that owes an Activity SF ID, the share that has one (100 with
// none owed), and each member's.
func (d *data) sfCompliance(ctx context.Context, db schooldirectory.Querier) (int, int, error) {
	// The team's share counts any non-empty SF ID; each member's, one that
	// is more than spaces (as the existing service reads the two).
	rows, err := db.Query(ctx, `SELECT COALESCE(responsible_staff_id, ''), COALESCE(salesforce_activity_id, '') <> '',
		COALESCE(btrim(salesforce_activity_id), '') <> '' FROM activity WHERE responsible_staff_id = ANY($1) AND fy = $2 AND activity_type = ANY($3) AND status = ANY($4)
		AND deleted_at IS NULL AND delivery_type IS DISTINCT FROM 'partner'`, d.t.ids(), d.fy, rules.SFRequiredTypes, rules.CompletedStatuses)
	if err != nil {
		return 0, 0, fmt.Errorf("teamtargets: the SF ID compliance: %w", err)
	}
	defer rows.Close()
	per := map[string][2]int{}
	required, have := 0, 0
	for rows.Next() {
		var who string
		var given, ok bool
		if err := rows.Scan(&who, &given, &ok); err != nil {
			return 0, 0, err
		}
		v := per[who]
		v[0]++
		required++
		if given {
			have++
		}
		if ok {
			v[1]++
		}
		per[who] = v
	}
	if err := rows.Err(); err != nil {
		return 0, 0, err
	}
	for _, r := range d.t.rows {
		tot, ok := 0, 0
		for _, id := range []string{r.member.UserID, r.member.StaffID} {
			if id != "" {
				tot += per[id][0]
				ok += per[id][1]
			}
		}
		r.sfCompliance, r.sfMiss = 100, tot-ok
		if tot > 0 {
			r.sfCompliance = pyRound(float64(ok) / float64(tot) * 100)
		}
	}
	if required == 0 {
		return 100, 0, nil
	}
	return pyRound(float64(have) / float64(required) * 100), required - have, nil
}

// core is the core-school packages: each plan of the portfolio's schools
// this year (not cancelled) and whether it keeps the year's pace less 20.
type core struct{ total, onTrack int }

func (d *data) corePackages(ctx context.Context, db schooldirectory.Querier) (core, error) {
	out := core{}
	fs, fe := targets.FYRange(d.fy)
	pace := 100
	if d.current {
		pace = d.roster.Pace(targets.Person{}, fs, fe, d.today)
	}
	rows, err := db.Query(ctx, `SELECT school_id, baseline_average IS NOT NULL, COALESCE(visits_completed, 0),
		COALESCE(trainings_completed, 0) FROM core_plan WHERE school_id = ANY($1) AND fy = $2 AND status NOT IN ('Cancelled', 'cancelled')`,
		d.port.codes, d.fy)
	if err != nil {
		return out, fmt.Errorf("teamtargets: the core plans: %w", err)
	}
	defer rows.Close()
	type plan struct {
		school string
		pct    int
	}
	plans := []plan{}
	for rows.Next() {
		var code string
		var baseline bool
		var visits, trainings int
		if err := rows.Scan(&code, &baseline, &visits, &trainings); err != nil {
			return out, err
		}
		done := min(4, visits) + min(4, trainings)
		if baseline {
			done++
		}
		pct := pyRound(float64(done) / 9 * 100)
		out.total++
		if pct >= max(0, pace-20) {
			out.onTrack++
		}
		name := d.port.names[code]
		if name == "" {
			name = code
		}
		plans = append(plans, plan{name, pct})
	}
	if err := rows.Err(); err != nil {
		return out, err
	}
	for _, r := range d.t.rows {
		names := map[string]bool{}
		for _, s := range r.schools {
			n := d.port.names[s.code]
			if n == "" {
				n = s.code
			}
			names[n] = true
		}
		sum, n := 0, 0
		for _, p := range plans {
			if names[p.school] {
				sum += p.pct
				n++
			}
		}
		if n > 0 {
			v := pyRound(float64(sum) / float64(n))
			r.corePct = &v
		}
	}
	return out, nil
}
