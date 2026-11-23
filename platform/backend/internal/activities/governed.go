package activities

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

const (
	// governedVisitKind is the workflow kind of the Business Transformation
	// visits the SSA recommendation can pin onto a Training Follow Up.
	governedVisitKind = "school_visit"
	fixedMappingMode  = "fixed"
)

// GovernedSupport answers what the recommendation says of a governed item at
// a school: its reason, and whether it is among the primary answers.
type GovernedSupport interface {
	GovernedWord(ctx context.Context, schoolCode, itemID string) (reason string, recommended bool, err error)
}

// WithGovernedSupport lets Go save a pinned governed visit.
func (s *Service) WithGovernedSupport(governed GovernedSupport) *Service {
	s.governed = governed
	return s
}

// governedVisit is the governed item Go takes: one fixed intervention, priced
// as a visit with no participants.
func (it item) governedVisit() bool {
	return !it.StandardSupport && it.WorkflowKind == governedVisitKind && !it.IsTrainingCourse &&
		!it.CountsTowardClientVisit && (it.ParticipantMode == "" || it.ParticipantMode == "none") &&
		len(it.Modes) == 1 && it.Modes[0] == fixedMappingMode
}

// governedSource is _create's recommendation source for governed support.
func governedSource(itemID string, need schoolNeed, recommended bool) map[string]any {
	var sourceSSA any
	verification := "none"
	if need.Record != nil && len(need.Ranked) > 0 {
		sourceSSA, verification = need.Record.ID, "confirmed"
	}
	return map[string]any{
		"engine": "apps.ssa.recommendation_engine", "sourceSsaId": sourceSSA, "verificationState": verification,
		"catalogueItemId": itemID, "recommended": recommended, "projectId": nil,
		"executorType": "staff", "context": "school",
	}
}

// primaryIntervention is the item's mapped intervention, which
// resolve_activity_intervention falls back on when the plan names none.
func primaryIntervention(ctx context.Context, q Querier, itemID string) (string, error) {
	var intervention string
	err := q.QueryRow(ctx, `SELECT COALESCE(intervention, '') FROM activity_intervention_mapping
WHERE catalogue_item_id = $1 AND active ORDER BY is_primary DESC, priority, id LIMIT 1`, itemID).Scan(&intervention)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("activities: reading the item's intervention: %w", err)
	}
	return intervention, nil
}
