package projectmonitoring

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// WatchedProjects is monitoring.watched_projects: the live projects this
// reader may watch, by name, as (id, name) — the choices Country Planning
// Oversight's tables narrow to.
func WatchedProjects(ctx context.Context, q schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope) ([][2]string, error) {
	projects, err := projectsFor(ctx, q, lensFor(p), scope)
	if err != nil {
		return nil, err
	}
	out := make([][2]string, 0, len(projects))
	for _, pr := range projects {
		out = append(out, [2]string{pr.ID, pr.Name})
	}
	return out, nil
}
