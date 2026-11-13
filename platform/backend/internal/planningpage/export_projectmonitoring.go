package planningpage

import (
	"context"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// WorkloadLine is the page's workload line (staff_plan.own_workload) for a
// page outside Planning that draws the same partial
// (partials/planning/_workload_line.html, internal/projectmonitoring); nil
// for a role that plans no visits.
func WorkloadLine(ctx context.Context, q schooldirectory.Querier, p auth.Principal, fy string) (*screensv1.PageBlock, error) {
	return workload(ctx, q, p, fy)
}
