package allocations

import (
	"context"
	"math/big"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// MasterPlanProgress is milestone_plan_progress(milestones, fy=fy) over
// every live activity: each milestone with an active rule, its planned,
// completed and verified figures against its own target (targets, by
// milestone id; nil when it has none).
func MasterPlanProgress(ctx context.Context, db schooldirectory.Querier, milestones []string, fy string,
	targets map[string]*big.Rat, today time.Time) (map[string]*Progress, error) {
	rulesOf, err := readRules(ctx, db, milestones)
	if err != nil {
		return nil, err
	}
	return planProgress(ctx, db, milestones, nil, rulesOf, fy, "a.deleted_at IS NULL", nil, targets, today)
}

// HolderActual is range_actual for one allocation over [start, end]: the
// verified figure its holder's work (a Programme Lead's team when team is
// set, else the person's own) earned towards the milestone's active rules.
func HolderActual(ctx context.Context, db schooldirectory.Querier, milestone, holderStaffID string, team bool,
	start, end time.Time) (pydecimal.Decimal, error) {
	owners, err := ownerIDs(ctx, db, holderStaffID, team)
	if err != nil {
		return pydecimal.Zero(), err
	}
	rulesOf, err := readRules(ctx, db, []string{milestone})
	if err != nil {
		return pydecimal.Zero(), err
	}
	bases := map[string]bool{}
	for _, r := range rulesOf[milestone] {
		bases[r.basis] = true
	}
	return rangeActual(ctx, db, milestone, bases, owners, []periodRow{{start: start, end: end}})
}
