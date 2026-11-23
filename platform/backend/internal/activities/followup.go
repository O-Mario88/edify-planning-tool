package activities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"

	"github.com/jackc/pgx/v5"
)

// The sessions a Training Follow Up may name (apps.activities.training_history).
var (
	followUpSourceStatuses = []string{
		"submitted_to_pl", "awaiting_ia_verification", "completed", "ia_verified", "accountant_confirmed", "closed",
	}
	clusterSessionTypes = []string{
		"cluster_training", "cluster_training_ssa_collection", "cluster_meeting", "cluster_meeting_ssa_review",
	}
	schoolTrainingTypes = []string{"training", "in_school_training", "school_improvement_training", "core_training"}
)

const (
	followUpPurpose       = "training_follow_up"
	followUpActivityType  = "training_follow_up_visit"
	sourceFocus           = "source_activity"
	sourceMissing         = "The selected source Activity does not exist."
	sourceFocusNotUsable  = "The selected session has no valid intervention to follow up. Ask IA to repair its completion record."
	sourceWrongKind       = "Training Follow Up must reference a completed training or cluster meeting this School took part in."
	sourceNotDelivered    = "Follow-up requires a completed source Training or support Activity."
	sourceOtherYear       = "Training Follow Up must reference a session from the same Fiscal Year as the scheduled visit."
	sourceNotAttended     = "This School is not recorded as attending the selected Cluster Training or Cluster Meeting."
	sourceAtAnotherSchool = "The selected training was delivered at a different School."
)

// followedSession is the session a Training Follow Up names.
type followedSession struct {
	ID, Type, Status, FY, SchoolID string
	Focus, PurposeFocus, SSAID     string
	Secondary                      []string
	Recommendation                 map[string]any
	// Attended: the completion register credits the school with the session.
	Attended bool
}

// problem is follow_up_source_problem: why this session cannot be followed
// up at this school in this year, or "".
func (a followedSession) problem(schoolID, fy string) string {
	cluster := in(clusterSessionTypes, a.Type)
	switch {
	case !cluster && !in(schoolTrainingTypes, a.Type):
		return sourceWrongKind
	case !in(followUpSourceStatuses, a.Status):
		return sourceNotDelivered
	case a.FY != fy:
		return sourceOtherYear
	case cluster && !a.Attended:
		return sourceNotAttended
	case !cluster && a.SchoolID != schoolID:
		return sourceAtAnotherSchool
	}
	return ""
}

// inherited is the intervention the follow-up takes from its session.
func (a followedSession) inherited() string {
	if a.Focus != "" {
		return a.Focus
	}
	return a.PurposeFocus
}

// inheritInto is apply_catalogue_snapshot's recommendation source: the
// session's, then this plan's, then the link back. Neither input changes.
func (a followedSession) inheritInto(own map[string]any) map[string]any {
	merged := make(map[string]any, len(a.Recommendation)+len(own)+1)
	maps.Copy(merged, a.Recommendation)
	maps.Copy(merged, own)
	merged["inheritedFromActivityId"] = a.ID
	return merged
}

// followedSessionFor reads and judges the session a request names; nil when it
// names none. Only a Training Follow Up's source is taken here.
func (s *Service) followedSessionFor(ctx context.Context, req Request, sc school, purpose, activityType, fy string) (*followedSession, error) {
	if req.SourceActivityID == "" {
		return nil, nil
	}
	if purpose != followUpPurpose && activityType != followUpActivityType {
		return nil, handOn("a source activity on work that is not a Training Follow Up")
	}
	source, err := readFollowedSession(ctx, s.db, req.SourceActivityID, sc.ID)
	if err != nil {
		return nil, err
	}
	if source == nil {
		return nil, refuse(sourceMissing)
	}
	if problem := source.problem(sc.ID, fy); problem != "" {
		return nil, refuse("%s", problem)
	}
	if focus := source.inherited(); focus != "" && !canonicalFocus(focus) {
		return nil, refuse(sourceFocusNotUsable)
	}
	return source, nil
}

func readFollowedSession(ctx context.Context, q Querier, id, schoolID string) (*followedSession, error) {
	var a followedSession
	var recommendation []byte
	var attended []string
	err := q.QueryRow(ctx, `SELECT id, activity_type, status, fy, COALESCE(school_id, ''),
  COALESCE(focus_intervention, ''), COALESCE(purpose_intervention, ''), COALESCE(source_ssa_id, ''),
  secondary_focus_interventions, recommendation_source, attended_school_ids
FROM activity WHERE id = $1 AND deleted_at IS NULL`, id).Scan(&a.ID, &a.Type, &a.Status, &a.FY, &a.SchoolID,
		&a.Focus, &a.PurposeFocus, &a.SSAID, &a.Secondary, &recommendation, &attended)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the source activity: %w", err)
	}
	if len(recommendation) > 0 {
		if err := json.Unmarshal(recommendation, &a.Recommendation); err != nil {
			return nil, fmt.Errorf("activities: reading the source's recommendation: %w", err)
		}
	}
	a.Attended = in(attended, schoolID)
	if !a.Attended {
		err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cluster_activity_attendance
WHERE activity_id = $1 AND school_id = $2 AND attended)`, id, schoolID).Scan(&a.Attended)
		if err != nil {
			return nil, fmt.Errorf("activities: reading the session's attendance: %w", err)
		}
	}
	return &a, nil
}
