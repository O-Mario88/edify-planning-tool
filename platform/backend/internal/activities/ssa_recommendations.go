package activities

// A confirmed assessment's recommendations, as the outbox handler
// `ssa.recommendations.generate` records them (apps.ssa.handlers →
// recommendation_service.supersede_stale, then generate_for_school with its
// limit of three): the school's live needs built on an older assessment are
// retired, then the engine's three most urgent interventions are recorded,
// or refreshed where a live recommendation already names the need. Inside
// the caller's transaction; idempotent, as the existing handler is.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	recommendationLimit    = 3
	recommendationValidity = 182 // days, DEFAULT_VALIDITY_DAYS
	recommendationEngine   = "recommendation_engine/2026-08"
	supersededReason       = "A newer confirmed assessment replaced it."
	unmappedRecommendation = "No published school-level activity answers this intervention."
)

// liveRecommendationStates are LIVE_STATES.
var liveRecommendationStates = []string{"generated", "accepted", "deferred", "planned"}

// priorSupportStatuses are PRIOR_SUPPORT_STATUSES.
var priorSupportStatuses = []string{"completed", "ia_verified", "accountant_confirmed", "closed"}

// GenerateSSARecommendations is the handler for one SSA record.
func GenerateSSARecommendations(ctx context.Context, tx pgx.Tx, recordID string, now time.Time, kampala *time.Location) error {
	_, err := generateFor(ctx, tx, recordID, now, kampala)
	return err
}

// generateFor is the handler's work, saying how many recommendations it
// recorded new.
func generateFor(ctx context.Context, tx pgx.Tx, recordID string, now time.Time, kampala *time.Location) (int, error) {
	var schoolID, status string
	var fy, clusterID *string
	err := tx.QueryRow(ctx, `SELECT r.school_id, r.verification_status, r.fy, s.cluster_id
FROM ssa_record r JOIN school s ON s.id = r.school_id WHERE r.id = $1`, recordID).Scan(&schoolID, &status, &fy, &clusterID)
	if errors.Is(err, pgx.ErrNoRows) {
		// The assessment or its school was removed after the event was raised.
		return 0, nil
	}
	if err != nil {
		return 0, fmt.Errorf("activities: reading the SSA record: %w", err)
	}
	if status != "confirmed" {
		return 0, nil
	}
	year := text(fy)
	if year == "" {
		year = schooldirectory.OperationalFY(now.In(kampala))
	}
	reader := pgNeed{q: tx}
	history, err := reader.confirmedHistory(ctx, schoolID)
	if err != nil {
		return 0, err
	}
	if len(history) == 0 {
		return 0, nil
	}
	current := latestApplicable(history)
	if err := supersedeStale(ctx, tx, schoolID, year, current.ID, now); err != nil {
		return 0, err
	}
	var peers []map[string]float64
	if text(clusterID) != "" {
		if peers, err = reader.peerScores(ctx, text(clusterID), schoolID); err != nil {
			return 0, err
		}
	}
	ranked := rankInterventions(history, peerStats(peers))
	if len(ranked) > recommendationLimit {
		ranked = ranked[:recommendationLimit]
	}
	prior, err := priorSupport(ctx, tx, schoolID)
	if err != nil {
		return 0, err
	}
	local := now.In(kampala)
	expires := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC).AddDate(0, 0, recommendationValidity)
	created := 0
	for i, need := range ranked {
		made, err := recordNeed(ctx, tx, schoolID, year, current.ID, i+1, need, prior[need.Intervention], expires, now)
		if err != nil {
			return created, err
		}
		if made {
			created++
		}
	}
	return created, nil
}

// supersedeStale retires the school's live recommendations for the year
// built on an assessment other than the current one.
func supersedeStale(ctx context.Context, tx pgx.Tx, schoolID, fy, currentRecord string, now time.Time) error {
	rows, err := tx.Query(ctx, `UPDATE ssa_recommendation SET state = 'superseded', decision_reason = $4, decided_at = $5,
  updated_at = $5
WHERE school_id = $1 AND fy = $2 AND state = ANY($3) AND ssa_record_id <> $6
RETURNING id, intervention`, schoolID, fy, liveRecommendationStates, supersededReason, now, currentRecord)
	if err != nil {
		return fmt.Errorf("activities: retiring the superseded recommendations: %w", err)
	}
	type retired struct{ id, intervention string }
	var gone []retired
	for rows.Next() {
		var r retired
		if err := rows.Scan(&r.id, &r.intervention); err != nil {
			rows.Close()
			return err
		}
		gone = append(gone, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, r := range gone {
		if err := recommendationAudit(ctx, tx, "ssa.recommendation_superseded", r.id, schoolID, r.intervention, "superseded", nil, now); err != nil {
			return err
		}
	}
	return nil
}

// priorSupport is _prior_support_counts: the school's delivered work by the
// intervention it focused on.
func priorSupport(ctx context.Context, tx pgx.Tx, schoolID string) (map[string]int, error) {
	rows, err := tx.Query(ctx, `SELECT focus_intervention, count(*)::int FROM activity
WHERE school_id = $1 AND deleted_at IS NULL AND status = ANY($2) AND COALESCE(focus_intervention, '') <> ''
GROUP BY focus_intervention`, schoolID, priorSupportStatuses)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the school's delivered support: %w", err)
	}
	defer rows.Close()
	counts := map[string]int{}
	for rows.Next() {
		var code string
		var n int
		if err := rows.Scan(&code, &n); err != nil {
			return nil, err
		}
		counts[code] = n
	}
	return counts, rows.Err()
}

// recordNeed refreshes the live recommendation for the need, or records a
// new one.
func recordNeed(ctx context.Context, tx pgx.Tx, schoolID, fy, recordID string, rank int, need rankedNeed, prior int,
	expires, now time.Time) (bool, error) {
	key := "ssa-rec:" + schoolID + ":" + fy + ":" + need.Intervention
	reason := explainNeed(need, prior)
	tag, err := tx.Exec(ctx, `UPDATE ssa_recommendation SET score = $2, score_band = $3, rank = $4, reason = $5, updated_at = $6
WHERE id = (SELECT id FROM ssa_recommendation WHERE condition_key = $1 AND state = ANY($7) ORDER BY id LIMIT 1)`,
		key, need.Score, need.Band, rank, reason, now, liveRecommendationStates)
	if err != nil {
		return false, fmt.Errorf("activities: refreshing a recommendation: %w", err)
	}
	if tag.RowsAffected() > 0 {
		return false, nil
	}
	var item *string
	if err := tx.QueryRow(ctx, `
SELECT i.id FROM activity_catalogue_item i JOIN activity_intervention_mapping m ON m.catalogue_item_id = i.id
WHERE m.intervention = $1 AND m.active AND i.status = 'active'
ORDER BY i.individual_school_allowed DESC, m.is_primary DESC, i.display_name LIMIT 1`, need.Intervention).Scan(&item); err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("activities: reading the activity that answers the need: %w", err)
	}
	unmapped := ""
	if item == nil {
		unmapped = unmappedRecommendation
	}
	var previous *string
	if err := tx.QueryRow(ctx, `SELECT id FROM ssa_recommendation WHERE condition_key = $1 AND NOT (state = ANY($2))
ORDER BY created_at DESC LIMIT 1`, key, liveRecommendationStates).Scan(&previous); err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("activities: reading the need's last recommendation: %w", err)
	}
	id := cuid.New()
	_, err = tx.Exec(ctx, `SAVEPOINT recommend`)
	if err != nil {
		return false, err
	}
	_, err = tx.Exec(ctx, `INSERT INTO ssa_recommendation (id, created_at, updated_at, condition_key, intervention, fy, score,
  score_band, rank, reason, unmapped_reason, state, decision_reason, expires_on, engine_version, recommended_item_id,
  school_id, ssa_record_id, supersedes_id)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'generated', '', $11, $12, $13, $14, $15, $16)`,
		id, now, key, need.Intervention, fy, need.Score, need.Band, rank, reason, unmapped,
		expires.Format(time.DateOnly), recommendationEngine, item, schoolID, recordID, previous)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		// A live recommendation for the need appeared meanwhile: refreshed.
		_, err = tx.Exec(ctx, `ROLLBACK TO SAVEPOINT recommend`)
		return false, err
	}
	if err != nil {
		return false, fmt.Errorf("activities: recording a recommendation: %w", err)
	}
	if _, err := tx.Exec(ctx, `RELEASE SAVEPOINT recommend`); err != nil {
		return false, err
	}
	return true, recommendationAudit(ctx, tx, "ssa.recommendation_generated", id, schoolID, need.Intervention, "generated",
		map[string]any{"rank": rank}, now)
}

// recommendationAudit is recommendation_service._audit, with no actor.
func recommendationAudit(ctx context.Context, tx pgx.Tx, action, id, schoolID, intervention, state string, extra map[string]any, now time.Time) error {
	payload := map[string]any{"school": schoolID, "intervention": intervention, "state": state}
	for k, v := range extra {
		payload[k] = v
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("ssa_recommendation"), SubjectID: audit.Text(id), Success: true,
		Payload: payload,
	}, now); err != nil {
		return fmt.Errorf("activities: writing the recommendation's audit row: %w", err)
	}
	return nil
}

// explainNeed is recommendation_service.explain.
func explainNeed(need rankedNeed, prior int) string {
	label := need.Label
	if label == "" {
		label = need.Intervention
	}
	band := need.Band
	if band == "" {
		band = "unscored"
	}
	parts := []string{fmt.Sprintf("%s scored %s (%s).", label, pyRepr(need.Score), band)}
	if peer := need.Components["peer_gap"]; peer.measurable && peer.zScore < 0 {
		parts = append(parts, fmt.Sprintf("It sits below the cluster average of %s across %d peer schools.",
			pyRepr(peer.peerMean), peer.peerCount))
	}
	if trend := need.Components["trend"]; trend.measurable && trend.direction == "declining" {
		parts = append(parts, "It has been declining across assessments.")
	}
	if p := need.Components["persistence"]; p.measurable && p.belowCount > 0 {
		parts = append(parts, fmt.Sprintf("It has stayed weak in %d of the last %d assessments.", p.belowCount, p.considered))
	}
	switch {
	case prior == 1:
		parts = append(parts, "1 previous support activity has not moved it.")
	case prior > 1:
		parts = append(parts, fmt.Sprintf("%d previous support activities have not moved it.", prior))
	default:
		parts = append(parts, "No support has been delivered against it yet.")
	}
	if need.Confidence != "" && need.Confidence != "high" {
		parts = append(parts, fmt.Sprintf("Confidence is %s — there are few assessments to compare.", need.Confidence))
	}
	return strings.Join(parts, " ")
}
