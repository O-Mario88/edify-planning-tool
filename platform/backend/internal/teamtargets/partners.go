package teamtargets

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// partnerRow is one Partner contribution row (_partner_rows).
type partnerRow struct {
	id, name, region, risk, tone            string
	assigned, scheduled, valid, pct, sf, ia int
}

// partners is _partner_rows: the year's live Partner work monitored by or
// on behalf of the team, by Partner, most assigned first.
func (d *data) partners(ctx context.Context, db schooldirectory.Querier) ([]partnerRow, error) {
	ids := d.t.ids()
	if len(ids) == 0 {
		return nil, nil
	}
	rows, err := db.Query(ctx, `SELECT assigned_partner_id, status, planned_date IS NOT NULL, COALESCE(btrim(salesforce_activity_id), '') <> '',
		COALESCE(activity_type, '') FROM activity WHERE fy = $1 AND deleted_at IS NULL AND delivery_type = 'partner'
		AND (monitored_by_staff_id = ANY($2) OR responsible_staff_id = ANY($2))
		AND assigned_partner_id IS NOT NULL AND assigned_partner_id <> '' AND status <> ALL($3) ORDER BY created_at DESC, id`, d.fy, ids, rules.NotInPlan)
	if err != nil {
		return nil, fmt.Errorf("teamtargets: the Partner work: %w", err)
	}
	type acc struct{ assigned, scheduled, valid, completed, sfOK, iaOK int }
	by, order := map[string]*acc{}, []string{}
	for rows.Next() {
		var pid, status, kind string
		var dated, sf bool
		if err := rows.Scan(&pid, &status, &dated, &sf, &kind); err != nil {
			rows.Close()
			return nil, err
		}
		a := by[pid]
		if a == nil {
			a = &acc{}
			by[pid] = a
			order = append(order, pid)
		}
		a.assigned++
		if dated && slices.Contains(rules.NotStarted, status) {
			a.scheduled++
		}
		if slices.Contains(rules.CompletedStatuses, status) {
			a.completed++
			if sf {
				a.sfOK++
			}
			if status == "ia_verified" || status == "verified" || status == "closed" {
				a.iaOK++
			}
			if sf && status != "awaiting_ia_verification" {
				a.valid++
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	names, regions, err := partnerNames(ctx, db, order)
	if err != nil {
		return nil, err
	}
	out := []partnerRow{}
	for _, pid := range order {
		a := by[pid]
		r := partnerRow{id: pid, name: "Partner", region: "—", assigned: a.assigned, scheduled: a.scheduled, valid: a.valid, sf: 100}
		if n, ok := names[pid]; ok {
			r.name, r.region = n, regions[pid]
			if r.region == "" {
				r.region = "—"
			}
		}
		if a.assigned > 0 {
			r.pct = pyRound(float64(a.valid) / float64(a.assigned) * 100)
		}
		if a.completed > 0 {
			r.sf = pyRound(float64(a.sfOK) / float64(a.completed) * 100)
			r.ia = pyRound(float64(a.iaOK) / float64(a.completed) * 100)
		}
		switch {
		case r.pct < 40:
			r.risk, r.tone = "Critical", "danger"
		case r.pct < 55:
			r.risk, r.tone = "High", "danger"
		case r.pct < 70:
			r.risk, r.tone = "Medium", "warning"
		default:
			r.risk, r.tone = "Low", "success"
		}
		out = append(out, r)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].assigned > out[j].assigned })
	return out, nil
}

// partnerNames are the Partners' names and region labels (", ".join of
// their regions, else the single column).
func partnerNames(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, map[string]string, error) {
	names, regions := map[string]string{}, map[string]string{}
	if len(ids) == 0 {
		return names, regions, nil
	}
	rows, err := db.Query(ctx, `SELECT id, COALESCE(name, ''), COALESCE(region_names, '{}'::varchar[]), COALESCE(region_name, '')
		FROM partner WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("teamtargets: the Partners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name, single string
		var many []string
		if err := rows.Scan(&id, &name, &many, &single); err != nil {
			return nil, nil, err
		}
		names[id] = name
		if len(many) == 0 && single != "" {
			many = []string{single}
		}
		regions[id] = strings.Join(many, ", ")
	}
	return names, regions, rows.Err()
}
