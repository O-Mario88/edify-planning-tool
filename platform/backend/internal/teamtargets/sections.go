package teamtargets

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// staffIDs are the team's People records.
func (t team) staffIDs() []string {
	out := []string{}
	for _, r := range t.rows {
		if r.member.StaffID != "" {
			out = append(out, r.member.StaffID)
		}
	}
	return out
}

// assigned is whether the team holds any Project priority this year
// (team_project_priorities) or any approved milestone allocation
// (team_milestone_targets). Go draws both sections only empty so far; a
// team with either is handed on.
func (d *data) assigned(ctx context.Context, db schooldirectory.Querier) (bool, error) {
	ids := d.t.staffIDs()
	if len(ids) == 0 {
		return false, nil
	}
	var found bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM project_staff_assignment a JOIN project p ON p.id = a.project_id
		WHERE a.staff_id = ANY($1) AND a.fy = $2 AND a.is_active AND p.deleted_at IS NULL AND p.status = ANY($3))
		OR EXISTS (SELECT 1 FROM hr_milestone_allocation a JOIN hr_priority_milestone m ON m.id = a.milestone_id
		  JOIN hr_strategic_priority sp ON sp.id = m.priority_id
		  WHERE a.status = 'approved' AND a.employee_id = ANY($1) AND sp.fy = $2)`,
		ids, d.fy, rules.LiveProjects).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("teamtargets: the team's Projects and milestones: %w", err)
	}
	return found, nil
}
