package activities

import (
	"context"
	"time"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// What the Core Schools forms (internal/coreforms) read of a school's need
// and of the year's planning policy.

// RankedNeed is one row of prioritized_interventions.
type RankedNeed struct {
	Intervention, Label string
	Score               float64
}

// SchoolNeed is plan_alignment.school_need: the ranked interventions, most
// urgent first, and the priority codes taken from them.
func SchoolNeed(ctx context.Context, q Querier, schoolID, clusterID string, now time.Time) ([]RankedNeed, []string, error) {
	need, err := schoolNeedOf(ctx, pgNeed{q}, schoolID, clusterID, now)
	if err != nil {
		return nil, nil, err
	}
	ranked := make([]RankedNeed, len(need.Ranked))
	for i, row := range need.Ranked {
		ranked[i] = RankedNeed{Intervention: row.Intervention, Label: row.Label, Score: row.Score}
	}
	return ranked, need.Priorities, nil
}

// FollowUpNeedsTraining is fy_policy.follow_up_requires_prior_training.
func FollowUpNeedsTraining(ctx context.Context, q Querier, place *registry.Work, fy string) (bool, error) {
	return followUpNeedsTraining(ctx, q, place, fy)
}
