package workplan

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// NextOpenFY is fy_policy.next_open_fy at noon of today in zone, or "" when
// no later year is open, for another page that opens on the planning year
// (the Planning Monitor), in the request's country.
func NextOpenFY(ctx context.Context, db schooldirectory.Querier, place *registry.Work, today time.Time, zone *time.Location) (string, error) {
	return nextOpenFY(ctx, db, place, today, zone)
}

// ScopedProjects is apps.projects.scoping.scoped_projects for the pages
// outside the Work Plan that offer a project choice: (id, name) by name.
func ScopedProjects(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope) ([][2]string, error) {
	return scopedProjects(ctx, db, p, scope)
}
