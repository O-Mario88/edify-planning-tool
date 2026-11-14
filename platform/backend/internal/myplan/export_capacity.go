package myplan

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// VisitTallies is staff_plan.visit_tallies' totals: for each person (a key
// of the caller's choosing mapped to their ids in both spaces), the counted
// visits they planned in fy, wherever the school is, by who planned them.
// Everyone asked for is in the answer, 0 when they planned none.
func VisitTallies(ctx context.Context, db schooldirectory.Querier, people map[string][]string, fy string) (map[string]int, error) {
	out := map[string]int{}
	keyOf := map[string]string{}
	for key, ids := range people {
		out[key] = 0
		for _, id := range ids {
			if id != "" {
				keyOf[id] = key
			}
		}
	}
	if len(keyOf) == 0 {
		return out, nil
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	if outside == nil {
		outside = []string{}
	}
	ids := make([]string, 0, len(keyOf))
	for id := range keyOf {
		ids = append(ids, id)
	}
	b := &sqlb{}
	where := "a.deleted_at IS NULL AND a.fy = " + b.arg(fy) + " AND a.responsible_staff_id = ANY(" + b.arg(ids) + ") AND " + countedVisit(b, outside)
	rows, err := db.Query(ctx, `SELECT a.responsible_staff_id, count(*) `+planFrom+` WHERE `+where+` GROUP BY 1`, b.args...)
	if err != nil {
		return nil, fmt.Errorf("myplan: counting each person's visits: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			return nil, fmt.Errorf("myplan: counting each person's visits: %w", err)
		}
		if key, ok := keyOf[id]; ok {
			out[key] += n
		}
	}
	return out, rows.Err()
}

// VisitTarget is rules.target_for(rules.planning_role(roles, active)): the
// visits a person plans in a year by the role they hold, a Programme Lead
// before a CCEO, 0 for anyone else.
func VisitTarget(roles []string, active string) int {
	held := append([]string{active}, roles...)
	switch {
	case in(held, rules.ProgramLeadRole):
		return rules.VisitTargets[rules.ProgramLeadRole]
	case in(held, rules.CCEORole):
		return rules.VisitTargets[rules.CCEORole]
	}
	return 0
}
