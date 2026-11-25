// Package btcases is the Business Transformation case work the outbox runs
// (apps.business_transformation.handlers): a verified SSA's weaknesses open
// a case and its recommendations.
package btcases

// `bt.ssa.confirmed` is ensure_case_from_verified_ssa: a confirmed
// assessment whose Financial Health or Government Requirements score is at
// or below the year's Uganda threshold converges on the school's one open
// case, one trigger for the assessment and one recommendation per kind; the
// Business Transformation officers and the Country Director are told when a
// recommendation is new. Inside the caller's transaction; replay converges
// on the same rows, as the existing handler's idempotency note says.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

const (
	financialHealth       = "financial_health"
	governmentRequirement = "government_requirement"
	uniqueViolation       = "23505"
	// defaultThreshold is BusinessTransformationPolicy's default score ceiling.
	defaultThreshold = "5.50"
)

// openCaseStatuses are OPEN_CASE_STATUSES.
var openCaseStatuses = []string{"recommended", "triage", "active", "monitoring", "deferred"}

// interventionLabels are SsaIntervention's labels for the two weaknesses.
var interventionLabels = map[string]string{
	financialHealth:       "Financial Health",
	governmentRequirement: "Government Requirements",
}

// recommendationKinds are the recommendations each weakness opens.
var recommendationKinds = map[string][]string{
	financialHealth:       {"financial_health_training", "loan_readiness"},
	governmentRequirement: {"compliance_support"},
}

// Notices is how the handler tells people: a phone copy per notice, and a
// logger for one that is not queued. Both may be nil.
type Notices struct {
	Push   activities.NoticePush
	Logger *slog.Logger
}

// weakness is one score at or below its threshold, both as Python prints
// them.
type weakness struct {
	intervention, score, threshold string
}

// assessment is the confirmed SSA record the event names.
type assessment struct {
	id, schoolID, schoolName, fy string
	actor                        *string
	verifiedAt                   *time.Time
	scores                       map[string]string
}

// EnsureCaseFromVerifiedSSA is the handler for one SSA record.
func EnsureCaseFromVerifiedSSA(ctx context.Context, tx pgx.Tx, recordID string, now time.Time, n Notices) error {
	rec, ok, err := readAssessment(ctx, tx, recordID)
	if err != nil || !ok {
		return err
	}
	finance, government, err := policyFor(ctx, tx, rec.fy, now)
	if err != nil {
		return err
	}
	weak, err := weaknesses(rec.scores, finance, government)
	if err != nil || len(weak) == 0 {
		return err
	}
	caseID, err := openCase(ctx, tx, rec, now)
	if err != nil {
		return err
	}
	triggerID, err := ensureTrigger(ctx, tx, rec, caseID, now)
	if err != nil {
		return err
	}
	created := 0
	for _, w := range weak {
		for _, kind := range recommendationKinds[w.intervention] {
			made, err := ensureRecommendation(ctx, tx, triggerID, caseID, kind, w, rec.fy, now)
			if err != nil {
				return err
			}
			if made {
				created++
			}
		}
	}
	if created == 0 {
		return nil
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "bt.ssa_recommendations_created", SubjectKind: audit.Text("TransformationCase"),
		SubjectID: audit.Text(caseID), ActorID: rec.actor, ActorRole: audit.Text("ImpactAssessment"), Success: true,
		Payload: map[string]any{"schoolId": rec.schoolID, "ssaId": rec.id, "recommendationsCreated": created},
	}, now); err != nil {
		return fmt.Errorf("btcases: writing the case's audit row: %w", err)
	}
	return notifyCase(ctx, tx, caseID, rec.schoolName, now, n)
}

// readAssessment reads the confirmed record and its scores; a record that is
// gone or no longer confirmed is nothing to do.
func readAssessment(ctx context.Context, tx pgx.Tx, recordID string) (assessment, bool, error) {
	rec := assessment{id: recordID, scores: map[string]string{}}
	var verifiedBy, uploadedBy *string
	err := tx.QueryRow(ctx, `SELECT r.school_id, s.name, r.fy, r.verified_by_user_id, r.uploaded_by, r.verified_at
FROM ssa_record r JOIN school s ON s.id = r.school_id
WHERE r.id = $1 AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL`, recordID).
		Scan(&rec.schoolID, &rec.schoolName, &rec.fy, &verifiedBy, &uploadedBy, &rec.verifiedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return rec, false, nil
	}
	if err != nil {
		return rec, false, fmt.Errorf("btcases: reading the SSA record: %w", err)
	}
	rec.actor = firstSet(verifiedBy, uploadedBy)
	rows, err := tx.Query(ctx, `SELECT intervention, score FROM ssa_score WHERE ssa_record_id = $1`, recordID)
	if err != nil {
		return rec, false, fmt.Errorf("btcases: reading the SSA scores: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var code string
		var score float64
		if err := rows.Scan(&code, &score); err != nil {
			return rec, false, err
		}
		rec.scores[code] = allocations.Repr(score)
	}
	return rec, true, rows.Err()
}

// firstSet is Python's `a or b` for two optional ids.
func firstSet(a, b *string) *string {
	if a != nil && *a != "" {
		return a
	}
	return b
}

// policyFor is policy_for_fy: the year's active Uganda policy, or the one
// its first use records with the default thresholds.
func policyFor(ctx context.Context, tx pgx.Tx, fy string, now time.Time) (finance, government string, err error) {
	err = tx.QueryRow(ctx, `SELECT financial_health_max_score::text, government_requirements_max_score::text FROM bt_policy
WHERE country_code = 'UG' AND fy = $1 AND active ORDER BY id LIMIT 1`, fy).Scan(&finance, &government)
	if err == nil {
		return finance, government, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return "", "", fmt.Errorf("btcases: reading the year's policy: %w", err)
	}
	err = tx.QueryRow(ctx, `
WITH made AS (
  INSERT INTO bt_policy (id, created_at, updated_at, country_code, fy, financial_health_max_score,
    government_requirements_max_score, loan_use_verification_days, active, created_by)
  VALUES ($1, $2, $2, 'UG', $3, $4::numeric, $4::numeric, 60, true, 'system')
  ON CONFLICT DO NOTHING
  RETURNING financial_health_max_score::text AS f, government_requirements_max_score::text AS g
)
SELECT f, g FROM made
UNION ALL
SELECT financial_health_max_score::text, government_requirements_max_score::text FROM bt_policy
WHERE country_code = 'UG' AND fy = $3 AND NOT EXISTS (SELECT 1 FROM made)
LIMIT 1`, cuid.New(), now, fy, defaultThreshold).Scan(&finance, &government)
	if err != nil {
		return "", "", fmt.Errorf("btcases: recording the year's policy: %w", err)
	}
	return finance, government, nil
}

// weaknesses are the scores at or below their thresholds, Financial Health
// first.
func weaknesses(scores map[string]string, finance, government string) ([]weakness, error) {
	var out []weakness
	for _, c := range []struct{ code, threshold string }{{financialHealth, finance}, {governmentRequirement, government}} {
		score, ok := scores[c.code]
		if !ok {
			continue
		}
		at, err := atOrBelow(score, c.threshold)
		if err != nil {
			return nil, err
		}
		if at {
			out = append(out, weakness{intervention: c.code, score: score, threshold: c.threshold})
		}
	}
	return out, nil
}

// atOrBelow compares two decimals exactly, as Decimal does.
func atOrBelow(score, threshold string) (bool, error) {
	s, ok := new(big.Rat).SetString(score)
	if !ok {
		return false, fmt.Errorf("btcases: the score %q is not a number", score)
	}
	t, ok := new(big.Rat).SetString(threshold)
	if !ok {
		return false, fmt.Errorf("btcases: the threshold %q is not a number", threshold)
	}
	return s.Cmp(t) <= 0, nil
}

// openCase is the school's open case, or the one opened for the assessment;
// a case opened meanwhile by another event is the one used.
func openCase(ctx context.Context, tx pgx.Tx, rec assessment, now time.Time) (string, error) {
	if id, ok, err := currentCase(ctx, tx, rec.schoolID); err != nil || ok {
		return id, err
	}
	id := cuid.New()
	if _, err := tx.Exec(ctx, `SAVEPOINT bt_case`); err != nil {
		return "", err
	}
	_, err := tx.Exec(ctx, `INSERT INTO bt_case (id, created_at, updated_at, source, environment, status, opened_fy,
  triage_decision, triage_reason, closure_reason, school_id)
VALUES ($1, $2, $2, 'manual_upload', 'production', 'recommended', $3, '', '', '', $4)`, id, now, rec.fy, rec.schoolID)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		if _, err := tx.Exec(ctx, `ROLLBACK TO SAVEPOINT bt_case`); err != nil {
			return "", err
		}
		id, ok, err := currentCase(ctx, tx, rec.schoolID)
		if err == nil && !ok {
			err = fmt.Errorf("btcases: the school %s has neither an open case nor room for one", rec.schoolID)
		}
		return id, err
	}
	if err != nil {
		return "", fmt.Errorf("btcases: opening the case: %w", err)
	}
	_, err = tx.Exec(ctx, `RELEASE SAVEPOINT bt_case`)
	return id, err
}

// currentCase is _open_case_for_school: the newest open case.
func currentCase(ctx context.Context, tx pgx.Tx, schoolID string) (string, bool, error) {
	var id string
	err := tx.QueryRow(ctx, `SELECT id FROM bt_case WHERE school_id = $1 AND status = ANY($2) AND deleted_at IS NULL
ORDER BY created_at DESC LIMIT 1`, schoolID, openCaseStatuses).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("btcases: reading the school's open case: %w", err)
	}
	return id, true, nil
}

// ensureTrigger is the assessment's trigger, recorded against the case the
// first time.
func ensureTrigger(ctx context.Context, tx pgx.Tx, rec assessment, caseID string, now time.Time) (string, error) {
	var verifiedAt *string
	if rec.verifiedAt != nil {
		v := pyISO(*rec.verifiedAt)
		verifiedAt = &v
	}
	snapshot := map[string]any{"ssaId": rec.id, "fy": rec.fy, "verifiedAt": verifiedAt, "scores": rec.scores}
	triggeredBy := "system"
	if rec.actor != nil {
		triggeredBy = *rec.actor
	}
	var id string
	err := tx.QueryRow(ctx, `
WITH made AS (
  INSERT INTO bt_case_trigger (id, created_at, updated_at, trigger_type, source_id, source_snapshot, triggered_by, case_id)
  VALUES ($1, $2, $2, 'verified_ssa', $3, $4, $5, $6)
  ON CONFLICT (trigger_type, source_id) DO NOTHING
  RETURNING id
)
SELECT id FROM made
UNION ALL
SELECT id FROM bt_case_trigger WHERE trigger_type = 'verified_ssa' AND source_id = $3 AND NOT EXISTS (SELECT 1 FROM made)
LIMIT 1`, cuid.New(), now, rec.id, snapshot, triggeredBy, caseID).Scan(&id)
	if err != nil {
		return "", fmt.Errorf("btcases: recording the case trigger: %w", err)
	}
	return id, nil
}

// pyISO is datetime.isoformat for an aware UTC time.
func pyISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}

// ensureRecommendation records the trigger's recommendation of a kind once.
func ensureRecommendation(ctx context.Context, tx pgx.Tx, triggerID, caseID, kind string, w weakness, fy string,
	now time.Time) (bool, error) {
	reason := fmt.Sprintf("Verified %s score %s is at or below the Uganda FY%s review threshold of %s.",
		interventionLabels[w.intervention], w.score, fy, w.threshold)
	tag, err := tx.Exec(ctx, `INSERT INTO bt_case_recommendation (id, created_at, updated_at, kind, status, reason,
  source_intervention, source_score, case_id, trigger_id)
VALUES ($1, $2, $2, $3, 'open', $4, $5, $6::numeric, $7, $8)
ON CONFLICT (trigger_id, kind) DO NOTHING`, cuid.New(), now, kind, reason, w.intervention, w.score, caseID, triggerID)
	if err != nil {
		return false, fmt.Errorf("btcases: recording a recommendation: %w", err)
	}
	return tag.RowsAffected() > 0, nil
}

// notifyCase is _notify_bt_case: every active Business Transformation
// officer and the Country Director, newest account first.
func notifyCase(ctx context.Context, tx pgx.Tx, caseID, schoolName string, now time.Time, n Notices) error {
	rows, err := tx.Query(ctx, `SELECT id FROM "user" WHERE is_active
  AND active_role IN ('BusinessTransformationOfficer', 'CountryDirector') ORDER BY created_at DESC`)
	if err != nil {
		return fmt.Errorf("btcases: reading who is told: %w", err)
	}
	var to []activities.NoticeTo
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		to = append(to, activities.NoticeTo{UserID: id, Route: "/business-transformation", Label: "Open Uganda Portfolio"})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	_, err = activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, caseID, activities.Notice{
		Title:       "Business Transformation review recommended",
		Body:        schoolName + " has a verified financial or compliance weakness to triage.",
		Event:       "bt.case.recommended",
		Category:    "business_transformation",
		ContextType: "TransformationCase",
		Priority:    "medium",
	}, to)
	return err
}
