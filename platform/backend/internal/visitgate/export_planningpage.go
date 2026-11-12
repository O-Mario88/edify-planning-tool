package visitgate

import "context"

// ProjectsOutsideSSA are the projects no SSA intervention measures
// (projects.models.projects_outside_ssa), for the Planning page's counted
// visits (internal/planningpage).
func ProjectsOutsideSSA(ctx context.Context, q Querier, r Rules) ([]string, error) {
	return projectsOutsideSSA(ctx, q, r)
}
