package schooldirectory

import (
	"context"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// What the bulk Add to Project drawer (internal/screens) borrows from the
// directory: the dialog's projects.

// BulkProjects are the Add to project dialog's projects for p, labelled and
// blocked as the directory offers them (assignable_projects,
// annotate_coordinator_names, annotate_allocations).
func BulkProjects(ctx context.Context, q Querier, p auth.Principal, s Scope) ([]*screensv1.BulkProjectChoice, error) {
	return bulkProjects(ctx, q, p, s)
}
