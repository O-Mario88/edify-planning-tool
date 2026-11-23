package activities

import (
	"context"
	"time"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// What the school scheduling forms (internal/coreforms) read of a school's
// need and of the year's planning policy.

// RankedNeed is one row of prioritized_interventions.
type RankedNeed struct {
	Intervention, Label, Band string
	Score                     float64
}

// NeedSummary is plan_alignment.school_need: the ranked interventions, most
// urgent first, the priority codes taken from them, and whether the verified
// SSA they rest on is out of date.
type NeedSummary struct {
	Ranked     []RankedNeed
	Priorities []string
	Stale      bool
}

// SchoolNeed reads a school's verified need.
func SchoolNeed(ctx context.Context, q Querier, schoolID, clusterID string, now time.Time) (NeedSummary, error) {
	need, err := schoolNeedOf(ctx, pgNeed{q}, schoolID, clusterID, now)
	if err != nil {
		return NeedSummary{}, err
	}
	ranked := make([]RankedNeed, len(need.Ranked))
	for i, row := range need.Ranked {
		ranked[i] = RankedNeed{Intervention: row.Intervention, Label: row.Label, Band: row.Band, Score: row.Score}
	}
	return NeedSummary{Ranked: ranked, Priorities: need.Priorities, Stale: need.Stale}, nil
}

// FollowUpNeedsTraining is fy_policy.follow_up_requires_prior_training.
func FollowUpNeedsTraining(ctx context.Context, q Querier, place *registry.Work, fy string) (bool, error) {
	return followUpNeedsTraining(ctx, q, place, fy)
}

// CostedKind is the workflow kind that prices kind (COSTED_AS).
func CostedKind(kind string) string {
	if costed, ok := rules.CostedAs[kind]; ok {
		return costed
	}
	return kind
}
