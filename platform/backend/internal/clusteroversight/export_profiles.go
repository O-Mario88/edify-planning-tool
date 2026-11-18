package clusteroversight

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// What the profiles of many schools (internal/schoolprofile) read from this
// page: Cluster Management's facts about each cluster of a scope
// (profile_intelligence.cluster_management over apps.clusters.scores), the
// same reads as Cluster Oversight and the cluster's own profile.

// ClusterCard is one cluster's attendance, scores and learners.
type ClusterCard struct {
	// Sessions are the year's delivered sessions with a register.
	Sessions int
	// Rate is the year's attendance out of 100, nil with no invitation.
	Rate                      *int
	Invited, Attended         int
	Teachers, Leaders, Absent int
	// Health and Impact are the composite scores, nil with too few parts.
	Health, Impact         *int
	HealthBand, ImpactBand string
	Maturity               int
	MaturityLabel          string
	// The cluster's schools' enrolment and learning results, like for
	// like, and its approved stories.
	EnrolmentCompared, EnrolmentBefore, EnrolmentAfter   int
	LearningCompared, LearningImproved, LearningDeclined int
	StoriesApproved                                      int
}

// CardReader reads clusters' cards from the database.
type CardReader struct{ DB schooldirectory.Querier }

// AlertAfter is MISSED_IN_A_ROW_ALERT: the sessions in a row a school must
// miss to be counted absent.
func (CardReader) AlertAfter() int { return rules.MissedInARowAlert }

// Cards reads each of the clusters' card for the year; today is the local
// day ("2026-11-18").
func (c CardReader) Cards(ctx context.Context, clusterIDs []string, fy, today string) (map[string]ClusterCard, error) {
	return Cards(ctx, c.DB, clusterIDs, fy, today)
}

// Cards reads each of the clusters' card for the year; today is the local
// day ("2026-11-18").
func Cards(ctx context.Context, q schooldirectory.Querier, clusterIDs []string, fy, today string) (map[string]ClusterCard, error) {
	out := map[string]ClusterCard{}
	if len(clusterIDs) == 0 {
		return out, nil
	}
	r, err := readClusters(ctx, q, func(b *sqlb) string { return "c.id = ANY(" + b.arg(clusterIDs) + ")" }, "LEFT", fy)
	if err != nil {
		return nil, err
	}
	ws := load(r, fy, today, nil)
	for _, c := range r.Clusters {
		f, card := ws.facts[c.ID], ws.cards[c.ID]
		a := f.attendance
		healthBand, _ := band(card.health.score())
		impactBand, _ := band(card.impact.score())
		out[c.ID] = ClusterCard{
			Sessions: len(a.sessions), Rate: a.rate, Invited: a.invitedTotal, Attended: a.attendedTotal,
			Teachers: a.teachers, Leaders: a.leaders, Absent: a.drifting,
			Health: card.health.score(), Impact: card.impact.score(), HealthBand: healthBand, ImpactBand: impactBand,
			Maturity: card.maturity, MaturityLabel: maturityLabel(card.maturity),
			EnrolmentCompared: f.enrolment.compared, EnrolmentBefore: f.enrolment.before, EnrolmentAfter: f.enrolment.after,
			LearningCompared: f.learning.compared, LearningImproved: f.learning.improved, LearningDeclined: f.learning.declined,
			StoriesApproved: f.stories.approved,
		}
	}
	return out, nil
}
