package coreforms

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

const (
	alternativeReason = "Authorized alternative Catalogue Activity."
	// primaryLimit is the `limit=3` _create asks recommend_activities for.
	primaryLimit = 3
)

// governedWord is what _create reads of the recommendation for a governed
// item: its reason, and whether it is among the primary answers.
func governedWord(all []Suggestion, itemID string) (string, bool) {
	reason, recommended := alternativeReason, false
	for i := len(all) - 1; i >= 0; i-- {
		if all[i].ID != itemID {
			continue
		}
		reason = all[i].Reason
		if i < primaryLimit {
			recommended = true
		}
	}
	return reason, recommended
}

// GovernedWord answers the save of a governed item at a school.
func (s *Service) GovernedWord(ctx context.Context, code, itemID string) (string, bool, error) {
	school, err := s.school(ctx, code)
	if err != nil {
		return "", false, fmt.Errorf("coreforms: reading the school: %w", err)
	}
	now := s.now()
	need, err := activities.SchoolNeed(ctx, s.db, school.ID, school.ClusterID, now)
	if err != nil {
		return "", false, fmt.Errorf("coreforms: reading the school's need: %w", err)
	}
	recommendation, _, err := s.recommendation(ctx, school, schooldirectory.OperationalFY(now), s.localDay(),
		need, schoolprofile.ActivityTypeLabels())
	if err != nil {
		return "", false, err
	}
	reason, recommended := governedWord(recommendation.All, itemID)
	return reason, recommended, nil
}
