package activities

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// RankedIntervention is one row of prioritized_interventions: the
// intervention and its latest score (rounded to one place).
type RankedIntervention struct {
	Intervention string
	Score        float64
}

// RankedInterventions is recommendation_engine.prioritized_interventions(
// school, n=limit): the school's interventions most urgent first, from its
// confirmed SSAs and its cluster's peers; none without a confirmed SSA or
// for a school that is gone.
func RankedInterventions(ctx context.Context, q Querier, schoolID string, limit int) ([]RankedIntervention, error) {
	var cluster string
	err := q.QueryRow(ctx, `SELECT COALESCE(cluster_id, '') FROM school WHERE id = $1`, schoolID).Scan(&cluster)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: the school's cluster: %w", err)
	}
	reader := pgNeed{q: q}
	history, err := reader.confirmedHistory(ctx, schoolID)
	if err != nil || len(history) == 0 {
		return nil, err
	}
	var peers []map[string]float64
	if cluster != "" {
		if peers, err = reader.peerScores(ctx, cluster, schoolID); err != nil {
			return nil, err
		}
	}
	ranked := rankInterventions(history, peerStats(peers))
	if limit >= 0 && len(ranked) > limit {
		ranked = ranked[:limit]
	}
	out := make([]RankedIntervention, len(ranked))
	for i, r := range ranked {
		out[i] = RankedIntervention{Intervention: r.Intervention, Score: r.Score}
	}
	return out, nil
}
