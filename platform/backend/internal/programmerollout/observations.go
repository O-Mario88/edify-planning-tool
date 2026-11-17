package programmerollout

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
)

// observation is one Regional Lead training observation shared with the
// lead (_observation_rows).
type observation struct {
	id, subject, recommendation string
	heldOn                      time.Time
	createdAt                   time.Time
	acknowledged                bool
	biblical                    *int
	average                     *float64
	// activity is the observed training, nil when the observation names none.
	activity                   *training
	courseID, partnerID, owner string
	isOpen                     bool
}

// observations is _observation_rows: the training observations of the year
// the Regional Lead shared with the lead, latest first. An administrator
// reads exactly what that lead reads (_observation_queryset).
func (s *Service) observations(ctx context.Context, sc *scope, fy string) ([]observation, error) {
	if sc.leadStaffID == "" {
		return nil, nil
	}
	ratings := "e." + strings.Join(rules.Observations.Criteria, ", e.")
	rows, err := s.db.Query(ctx, `SELECT e.id, COALESCE(e.subject, ''), COALESCE(e.recommendation, ''), e.held_on, e.created_at,
  e.acknowledged_at IS NOT NULL, `+ratings+`, a.id IS NOT NULL,
  COALESCE(a.activity_type, ''), COALESCE(a.activity_name_snapshot, ''), COALESCE(a.delivery_type, ''), COALESCE(a.assigned_partner_id, ''),
  COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.school_id, ''), COALESCE(s.name, ''),
  COALESCE(cl.name, ''), COALESCE(a.training_course_id, ''), COALESCE(a.catalogue_item_id, ''), COALESCE(ci.is_training_course, FALSE)
FROM cce_regional_engagement e LEFT JOIN activity a ON a.id = e.activity_id LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE e.kind = $1 AND e.feedback_shared_at IS NOT NULL AND e.program_lead_ids @> ARRAY[$2]::varchar[] AND e.fy = $3
ORDER BY e.held_on DESC, e.created_at DESC`, rules.ObservationKind, sc.leadStaffID, fy)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the observations: %w", err)
	}
	defer rows.Close()
	out := []observation{}
	for rows.Next() {
		var o observation
		var t training
		var hasActivity bool
		scores := make([]*int, len(rules.Observations.Criteria))
		dest := []any{&o.id, &o.subject, &o.recommendation, &o.heldOn, &o.createdAt, &o.acknowledged}
		for i := range scores {
			dest = append(dest, &scores[i])
		}
		dest = append(dest, &hasActivity, &t.kind, &t.snapshot, &t.delivery, &t.partner, &t.responsible, &t.monitor,
			&t.schoolID, &t.schoolName, &t.clusterName, &t.course, &t.catalogue, &t.courseItem)
		if err := rows.Scan(dest...); err != nil {
			return nil, fmt.Errorf("programmerollout: reading an observation: %w", err)
		}
		o.biblical = scores[0]
		o.average = meanInts(scores)
		if hasActivity {
			o.activity = &t
		}
		o.courseID = t.courseID()
		if t.delivery == "partner" {
			o.partnerID = t.partner
		}
		o.owner = sc.attribute(t.responsible, t.monitor, t.schoolID)
		o.isOpen = slices.Contains(rules.Observations.ChangeRecommendations, o.recommendation) && !o.acknowledged
		out = append(out, o)
	}
	return out, rows.Err()
}

// meanInts is _mean over ratings: the average of those given, to one place.
func meanInts(values []*int) *float64 {
	given := []float64{}
	for _, v := range values {
		if v != nil {
			given = append(given, float64(*v))
		}
	}
	return mean(given)
}

// meanOf is _mean over averages that may be missing.
func meanOf(values []*float64) *float64 {
	given := []float64{}
	for _, v := range values {
		if v != nil {
			given = append(given, *v)
		}
	}
	return mean(given)
}

// observationFold is _observation_fold.
type observationFold struct {
	observed, open   int
	rating, biblical *float64
}

func foldObservations(rows []observation) observationFold {
	f := observationFold{observed: len(rows)}
	averages, biblical := []*float64{}, []*int{}
	for _, o := range rows {
		averages = append(averages, o.average)
		biblical = append(biblical, o.biblical)
		if o.isOpen {
			f.open++
		}
	}
	f.rating, f.biblical = meanOf(averages), meanInts(biblical)
	return f
}

// pyFloat is str() of a float: "3.0", "2.5".
func pyFloat(v float64) string { return allocations.Repr(v) }

// ofFour is "{rating} of 4", or "—" without one.
func ofFour(v *float64) string {
	if v == nil {
		return "—"
	}
	return pyFloat(*v) + " of 4"
}

// observedTraining is _observation_training: the training's name and where
// it was held, or the observation's subject when it names no training.
func observedTraining(o observation, byID map[string]course) string {
	if o.activity == nil {
		return o.subject
	}
	parts := []string{}
	for _, part := range []string{trainingName(*o.activity, byID), orElse(o.activity.schoolName, o.activity.clusterName)} {
		if part != "" {
			parts = append(parts, part)
		}
	}
	return strings.Join(parts, " · ")
}

// feedbackState is _feedback_state.
func feedbackState(o observation, sc *scope) string {
	switch {
	case o.acknowledged:
		return "Answered"
	case sc.support:
		return "Awaiting the Programme Lead"
	}
	return "Awaiting your answer"
}

// observationTrainings is the observed trainings, for the names the rows
// need.
func observationTrainings(rows []observation) []training {
	out := []training{}
	for _, o := range rows {
		if o.activity != nil {
			out = append(out, *o.activity)
		}
	}
	return out
}

// followUps is _partner_follow_ups: the latest partner engagement the lead
// recorded in answer to each observation with a recommendation.
func (s *Service) followUps(ctx context.Context, sc *scope, rows []observation) (map[string]time.Time, error) {
	out := map[string]time.Time{}
	ids := []string{}
	for _, o := range rows {
		if o.recommendation != "" {
			ids = append(ids, o.id)
		}
	}
	if len(ids) == 0 || sc.leadUserID == "" {
		return out, nil
	}
	found, err := s.db.Query(ctx, `SELECT source_engagement_id, held_on FROM partner_engagement
WHERE author_id = $1 AND source_engagement_id = ANY($2)`, sc.leadUserID, ids)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the partner follow-ups: %w", err)
	}
	defer found.Close()
	for found.Next() {
		var id string
		var held time.Time
		if err := found.Scan(&id, &held); err != nil {
			return nil, fmt.Errorf("programmerollout: reading a partner follow-up: %w", err)
		}
		if latest, ok := out[id]; !ok || held.After(latest) {
			out[id] = held
		}
	}
	return out, found.Err()
}
