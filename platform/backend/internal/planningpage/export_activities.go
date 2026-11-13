package planningpage

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// What the school-visit save (internal/activities) reads from the Planning
// page: the person's counted visits for a year and their role's ceiling, as
// the page's workload line shows them (staff_plan.own_workload), for the
// warning a save's confirmation carries (staff_plan.ceiling_notice).

// VisitCeiling is the person's counted visits for fy and their ceiling;
// ceiling 0 for a role that plans no visits.
func VisitCeiling(ctx context.Context, q schooldirectory.Querier, p auth.Principal, fy string) (planned, ceiling int, err error) {
	w, ok, err := readWorkload(ctx, q, p, fy)
	if err != nil || !ok {
		return 0, 0, err
	}
	return w.planned(), w.ceiling, nil
}
