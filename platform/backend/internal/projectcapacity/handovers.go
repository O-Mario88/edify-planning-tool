package projectcapacity

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// HandoverRoute is one open project a school is enrolled in: a way to hand
// its support to a partner.
type HandoverRoute struct {
	AssignmentID, Project string
}

// HandoverRoutes is planning_views.project_handover_routes for the projects
// this reader may plan in.
func (s *Service) HandoverRoutes(ctx context.Context, schoolPK string, projectIDs []string) ([]HandoverRoute, error) {
	if len(projectIDs) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT a.id, pr.name FROM project_school_assignment a
JOIN project pr ON pr.id = a.project_id
WHERE a.school_id = $1 AND a.project_id = ANY($2) AND pr.status = ANY($3)
ORDER BY pr.name`, schoolPK, projectIDs, rules.OpenStatuses)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the school's projects: %w", err)
	}
	routes, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (HandoverRoute, error) {
		var route HandoverRoute
		err := row.Scan(&route.AssignmentID, &route.Project)
		return route, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading a school's project: %w", err)
	}
	return routes, nil
}
