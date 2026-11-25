// Package projectimpact is the Special Project impact work the outbox runs
// (apps.projects.handlers and apps.projects.baselines): an enrolment's
// baseline captured from a confirmed assessment taken before the school
// joined, and its verdict re-derived when a delivery is verified or an
// assessment confirmed.
package projectimpact

// Two handlers. `projects.baselines.capture` is capture_missing_baselines for
// one school: every enrolment with no baseline and an intervention takes the
// latest confirmed reading dated on or before its start, never overwriting
// one captured meanwhile; when one is filled the school's impact is refreshed
// in the same transaction. `projects.impact.refresh` is refresh_school_impact:
// each enrolment with a baseline is stamped once with the rule its first
// verified delivery resolves (stamp_measurement_rule) and classified under
// it (refresh_follow_up). Inside the caller's transaction; replay converges.

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	improved           = "improved"
	noChange           = "no_change"
	declined           = "declined"
	maintainedStrong   = "maintained_strong"
	notYetMeasurable   = "not_yet_measurable"
	insufficient       = "insufficient_evidence"
	maintainDirection  = "maintain_strong"
	eligibilityOnly    = "eligibility_only"
	strongScore        = 8.0
	minIntervalDays    = 120 // change_rules.MIN_INTERVAL_DAYS
	scoreMin, scoreMax = 0.0, 10.0
)

// measured are MEASURED: verdicts on the school, not on the evidence.
var measured = []string{improved, noChange, declined, maintainedStrong}

// verifiedStates are the delivery states that count as the project having
// reached the school.
var verifiedStates = []string{"ia_verified", "accountant_confirmed", "closed"}

// scoreBand is ssa_score_band's label.
func scoreBand(score float64) string {
	switch {
	case score >= 8.0:
		return "Strong"
	case score >= 6.0:
		return "Improving"
	case score >= 5.0:
		return "Warning"
	}
	return "Critical"
}

// enrolment is one ProjectSchoolAssignment as the refresh reads it.
type enrolment struct {
	id, projectID, schoolID string
	intervention            string
	classification          string
	mappingID               *string
	baselineSSA             *string
	baselineScore           *float64
	country                 string
}

// rule is one ActivityInterventionMapping's measurement fields.
type rule struct {
	id                          string
	version                     int
	minDays, expectedDays, maxD *int
	direction, role             string
	threshold                   *float64
}

// RefreshSchoolImpact is the `projects.impact.refresh` handler for one
// school; it says how many enrolments it measured.
func RefreshSchoolImpact(ctx context.Context, tx pgx.Tx, schoolID string, kampala *time.Location, now time.Time) (int, error) {
	rows, err := tx.Query(ctx, `
SELECT a.id, a.project_id, a.school_id, COALESCE(NULLIF(a.matched_intervention, ''), p.intervention, ''),
  a.impact_classification, a.mapping_id, a.baseline_ssa_id, a.baseline_score, COALESCE(r.country, '')
FROM project_school_assignment a
JOIN project p ON p.id = a.project_id
JOIN school s ON s.id = a.school_id
LEFT JOIN region r ON r.id = s.region_id
WHERE a.school_id = $1 AND a.baseline_score IS NOT NULL
ORDER BY a.id`, schoolID)
	if err != nil {
		return 0, fmt.Errorf("projectimpact: reading the school's enrolments: %w", err)
	}
	var list []enrolment
	for rows.Next() {
		var e enrolment
		if err := rows.Scan(&e.id, &e.projectID, &e.schoolID, &e.intervention, &e.classification, &e.mappingID,
			&e.baselineSSA, &e.baselineScore, &e.country); err != nil {
			rows.Close()
			return 0, err
		}
		e.country = strings.TrimSpace(e.country)
		list = append(list, e)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	for _, e := range list {
		r, err := stampRule(ctx, tx, e)
		if err != nil {
			return 0, err
		}
		if err := refreshFollowUp(ctx, tx, e, r, kampala, now); err != nil {
			return 0, err
		}
	}
	return len(list), nil
}

// delivery is the first verified delivery of the project at the school.
type delivery struct {
	on     time.Time
	itemID *string
}

// firstVerified is _first_verified: the earliest by delivery day, then by
// the planned day; a delivery with neither is none.
func firstVerified(ctx context.Context, tx pgx.Tx, e enrolment) (*delivery, error) {
	var actual, scheduled *time.Time
	var item *string
	err := tx.QueryRow(ctx, `SELECT actual_delivery_date, scheduled_date, catalogue_item_id FROM activity
WHERE school_id = $1 AND project_id = $2 AND status = ANY($3) AND deleted_at IS NULL
ORDER BY actual_delivery_date, scheduled_date LIMIT 1`, e.schoolID, e.projectID, verifiedStates).Scan(&actual, &scheduled, &item)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("projectimpact: reading the first verified delivery: %w", err)
	}
	switch {
	case actual != nil:
		return &delivery{on: dayOf(*actual), itemID: item}, nil
	case scheduled != nil:
		// A timestamp's date as Django reads it: the UTC day.
		return &delivery{on: dayOf(scheduled.UTC()), itemID: item}, nil
	}
	return nil, nil
}

func dayOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// stampRule is stamp_measurement_rule: the enrolment's stamped rule, or the
// one its first verified delivery resolves now, written once; none while
// the enrolment already has a measured verdict.
func stampRule(ctx context.Context, tx pgx.Tx, e enrolment) (*rule, error) {
	if e.mappingID != nil {
		return readRule(ctx, tx, `WHERE id = $1`, *e.mappingID)
	}
	if contains(measured, e.classification) || e.intervention == "" {
		return nil, nil
	}
	found, err := firstVerified(ctx, tx, e)
	if err != nil || found == nil || found.itemID == nil || *found.itemID == "" {
		return nil, err
	}
	r, err := ruleForActivity(ctx, tx, *found.itemID, e.intervention, e.country)
	if err != nil || r == nil {
		return nil, err
	}
	if _, err := tx.Exec(ctx, `UPDATE project_school_assignment SET mapping_id = $2, mapping_version = $3
WHERE id = $1 AND mapping_id IS NULL`, e.id, r.id, r.version); err != nil {
		return nil, fmt.Errorf("projectimpact: stamping the enrolment's rule: %w", err)
	}
	return r, nil
}

const ruleColumns = `SELECT id, version, follow_up_min_days, follow_up_expected_days, follow_up_max_days,
  expected_direction, measurement_role, min_meaningful_change::float8, intervention, country
FROM activity_intervention_mapping `

type ruleRow struct {
	rule
	intervention *string
	country      string
}

func scanRules(rows pgx.Rows) ([]ruleRow, error) {
	defer rows.Close()
	var out []ruleRow
	for rows.Next() {
		var r ruleRow
		if err := rows.Scan(&r.id, &r.version, &r.minDays, &r.expectedDays, &r.maxD, &r.direction, &r.role,
			&r.threshold, &r.intervention, &r.country); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func readRule(ctx context.Context, tx pgx.Tx, where string, args ...any) (*rule, error) {
	rows, err := tx.Query(ctx, ruleColumns+where, args...)
	if err != nil {
		return nil, fmt.Errorf("projectimpact: reading the measurement rule: %w", err)
	}
	found, err := scanRules(rows)
	if err != nil || len(found) == 0 {
		return nil, err
	}
	return &found[0].rule, nil
}

// ruleForActivity is change_rules.rule_for_activity: the published rows for
// the delivered item, naming the intervention or none, newest first; the
// school's country first, then the deployment-wide rule, a row naming the
// intervention before one that names none.
func ruleForActivity(ctx context.Context, tx pgx.Tx, itemID, intervention, country string) (*rule, error) {
	rows, err := tx.Query(ctx, ruleColumns+`WHERE status = 'published' AND active AND catalogue_item_id = $1
  AND (intervention = $2 OR intervention IS NULL) AND NOT (not_ssa_measured_reason > '')
ORDER BY effective_from DESC, version DESC, updated_at DESC`, itemID, intervention)
	if err != nil {
		return nil, fmt.Errorf("projectimpact: reading the item's measurement rules: %w", err)
	}
	all, err := scanRules(rows)
	if err != nil {
		return nil, err
	}
	pick := func(want string) *rule {
		var pool []ruleRow
		for _, r := range all {
			if r.country == want {
				pool = append(pool, r)
			}
		}
		for _, r := range pool {
			if r.intervention != nil && *r.intervention == intervention {
				return &r.rule
			}
		}
		if len(pool) > 0 {
			return &pool[0].rule
		}
		return nil
	}
	if country != "" {
		if r := pick(country); r != nil {
			return r, nil
		}
	}
	return pick(""), nil
}

// reading is one confirmed assessment's score on the intervention.
type reading struct {
	recordID string
	on       time.Time
	score    float64
}

// readingsFor is ssa_impact._readings: the school's confirmed readings on
// the intervention, oldest first, each on its UTC day.
func readingsFor(ctx context.Context, tx pgx.Tx, schoolID, intervention string) ([]reading, error) {
	rows, err := tx.Query(ctx, `SELECT r.id, r.date_of_ssa, s.score FROM ssa_score s JOIN ssa_record r ON r.id = s.ssa_record_id
WHERE r.school_id = $1 AND r.verification_status = 'confirmed' AND s.intervention = $2
ORDER BY r.date_of_ssa`, schoolID, intervention)
	if err != nil {
		return nil, fmt.Errorf("projectimpact: reading the school's assessments: %w", err)
	}
	defer rows.Close()
	var out []reading
	for rows.Next() {
		var rd reading
		var on *time.Time
		if err := rows.Scan(&rd.recordID, &on, &rd.score); err != nil {
			return nil, err
		}
		if on == nil || rd.score < scoreMin || rd.score > scoreMax {
			continue
		}
		rd.on = dayOf(on.UTC())
		out = append(out, rd)
	}
	return out, rows.Err()
}

// refreshFollowUp is refresh_follow_up: the enrolment's verdict and the day
// its follow-up is due, and the assessment that judges it when there is one.
func refreshFollowUp(ctx context.Context, tx pgx.Tx, e enrolment, r *rule, kampala *time.Location, now time.Time) error {
	if e.intervention == "" || e.baselineScore == nil {
		return nil
	}
	found, err := firstVerified(ctx, tx, e)
	if err != nil || found == nil {
		return err
	}
	delivered := found.on
	var minDays, expectedDays, maxDays *int
	direction, role := "improve", ""
	var threshold *float64
	if r != nil {
		minDays, expectedDays, maxDays = r.minDays, r.expectedDays, r.maxD
		direction, role, threshold = r.direction, r.role, r.threshold
	}
	if minDays == nil {
		baselineOn, err := baselineDay(ctx, tx, e)
		if err != nil {
			return err
		}
		if baselineOn != nil {
			gap := int(baselineOn.AddDate(0, 0, minIntervalDays).Sub(delivered).Hours() / 24)
			if gap > 0 {
				minDays = &gap
			}
		}
	}
	readings, err := readingsFor(ctx, tx, e.schoolID, e.intervention)
	if err != nil {
		return err
	}
	followUp := followUpFor(readings, delivered, minDays, maxDays)
	today := dayOf(now.In(kampala))
	windowOpen := minDays == nil || !today.Before(delivered.AddDate(0, 0, *minDays))
	verdict := judge(*e.baselineScore, followUp, direction, role, threshold, windowOpen)
	dueAfter := expectedDays
	if dueAfter == nil {
		dueAfter = minDays
	}
	due := delivered
	if dueAfter != nil && *dueAfter != 0 {
		due = delivered.AddDate(0, 0, *dueAfter)
	}
	if followUp == nil {
		_, err = tx.Exec(ctx, `UPDATE project_school_assignment SET impact_classification = $2, follow_up_due_on = $3
WHERE id = $1`, e.id, verdict, due.Format(time.DateOnly))
	} else {
		_, err = tx.Exec(ctx, `UPDATE project_school_assignment SET impact_classification = $2, follow_up_due_on = $3,
  follow_up_ssa_id = $4, follow_up_score = $5 WHERE id = $1`, e.id, verdict, due.Format(time.DateOnly),
			followUp.recordID, followUp.score)
	}
	if err != nil {
		return fmt.Errorf("projectimpact: writing the enrolment's verdict: %w", err)
	}
	return nil
}

// baselineDay is _baseline_date: the UTC day of the baseline assessment.
func baselineDay(ctx context.Context, tx pgx.Tx, e enrolment) (*time.Time, error) {
	if e.baselineSSA == nil || *e.baselineSSA == "" {
		return nil, nil
	}
	var on *time.Time
	err := tx.QueryRow(ctx, `SELECT date_of_ssa FROM ssa_record WHERE id = $1`, *e.baselineSSA).Scan(&on)
	if errors.Is(err, pgx.ErrNoRows) || on == nil {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("projectimpact: reading the baseline assessment: %w", err)
	}
	day := dayOf(on.UTC())
	return &day, nil
}

// followUpFor is follow_up_for: the first reading inside the window after
// the delivery; a window bound of zero days is no bound.
func followUpFor(readings []reading, after time.Time, minDays, maxDays *int) *reading {
	earliest := after
	if minDays != nil && *minDays != 0 {
		earliest = after.AddDate(0, 0, *minDays)
	}
	var latest *time.Time
	if maxDays != nil && *maxDays != 0 {
		l := after.AddDate(0, 0, *maxDays)
		latest = &l
	}
	for i := range readings {
		rd := readings[i]
		if rd.on.Before(earliest) {
			continue
		}
		if latest != nil && rd.on.After(*latest) {
			return nil
		}
		return &rd
	}
	return nil
}

// judge is classify (or the eligibility-only verdict) for a baseline that is
// present.
func judge(baseline float64, followUp *reading, direction, role string, threshold *float64, windowOpen bool) string {
	if role == eligibilityOnly {
		if followUp == nil && !windowOpen {
			return notYetMeasurable
		}
		return insufficient
	}
	if followUp == nil {
		if !windowOpen {
			return notYetMeasurable
		}
		return insufficient
	}
	return changeBetween(baseline, followUp.score, direction, threshold)
}

// changeBetween is change_rules.change_between for two present readings.
func changeBetween(before, after float64, direction string, threshold *float64) string {
	delta := pyRound2(after - before)
	if direction == "" {
		direction = "improve"
	}
	if direction == maintainDirection {
		if after >= strongScore {
			return maintainedStrong
		}
		return declined
	}
	if threshold != nil {
		t := math.Abs(*threshold)
		switch {
		case delta >= t:
			return improved
		case delta <= -t:
			return declined
		}
		return noChange
	}
	switch {
	case delta > 0:
		return improved
	case delta < 0:
		return declined
	}
	return noChange
}

func contains(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// pyRound2 is round(x, 2) of a float: correctly rounded from its exact
// value, as Python rounds.
func pyRound2(x float64) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', 2, 64), 64)
	return v
}
