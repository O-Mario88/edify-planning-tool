package actionsweep

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningoversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// action is one TeamAction as the sweep reads it.
type action struct {
	id, key, issue, school, fy          string
	sender, recipient, requested, route string
	due                                 *time.Time
}

// interventionLimit is prioritized_interventions(school, n=20).
const interventionLimit = 20

// stillHolds is condition_still_holds: the source of truth read again;
// true means the problem is still there (and an issue the system may not
// settle always is).
func stillHolds(ctx context.Context, db schooldirectory.Querier, a action, today, now time.Time) (bool, error) {
	switch {
	case !in(rules.SystemVerifiable, a.issue):
		return true, nil
	case in(rules.OversightRiskKeys, a.issue):
		kind, id, ok := parseKey(a.key)
		if !ok {
			return true, nil
		}
		keys, found, err := planningoversight.NewService(db, func() time.Time { return now }).RecordRiskKeys(ctx, kind, id, today)
		if err != nil || !found {
			return false, err
		}
		return in(keys, a.issue), nil
	case in(rules.PartnerOversightRiskKeys, a.issue):
		_, id, ok := parseKey(a.key)
		if !ok {
			return true, nil
		}
		keys, found, err := partneroversight.AssignmentRiskKeys(ctx, db, id, today)
		if err != nil || !found {
			return false, err
		}
		// The detector names the risk without the playbook's prefix.
		return in(keys, a.issue) || in(keys, strings.TrimPrefix(a.issue, "partner_")), nil
	case in(rules.CoreOversightRiskKeys, a.issue):
		return coreStillShort(ctx, db, a)
	case in(rules.PlanningGapKeys, a.issue):
		return planningmonitor.SchoolGapOpen(ctx, db, a.school, a.fy, rules.SchoolGapFigure[a.issue], today)
	}
	switch a.issue {
	case "no_ssa":
		var has bool
		err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM ssa_record WHERE school_id = $1 AND fy = $2
  AND verification_status = 'confirmed' AND deleted_at IS NULL)`, a.school, a.fy).Scan(&has)
		return !has, err
	case "no_visit":
		done, err := verifiedWork(ctx, db, a, rules.VisitTypes)
		return !done, err
	case "no_training":
		done, err := verifiedWork(ctx, db, a, rules.TrainingTypes)
		return !done, err
	case "no_visit_or_training":
		visits, err := verifiedWork(ctx, db, a, rules.VisitTypes)
		if err != nil || visits {
			return false, err
		}
		trainings, err := verifiedWork(ctx, db, a, rules.TrainingTypes)
		return !trainings, err
	case "low_ssa", "intervention_critical", "intervention_warning":
		return interventionStillWeak(ctx, db, a)
	}
	return true, nil
}

// parseKey is parse_oversight_condition_key: (kind, id) of a key the
// oversight pages wrote.
func parseKey(key string) (string, string, bool) {
	parts := strings.Split(key, "|")
	if len(parts) != 4 || !in(rules.OversightKeyPrefixes, parts[0]) {
		return "", "", false
	}
	return parts[2], parts[3], true
}

// verifiedWork is _done: the school has work of these kinds verified this
// year.
func verifiedWork(ctx context.Context, db schooldirectory.Querier, a action, kinds []string) (bool, error) {
	var done bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE school_id = $1 AND activity_type = ANY($2) AND fy = $3
  AND status = ANY($4) AND deleted_at IS NULL)`, a.school, kinds, a.fy, rules.IAVerifiedStatuses).Scan(&done)
	if err != nil {
		return false, fmt.Errorf("actionsweep: the school's verified work: %w", err)
	}
	return done, nil
}

// coreStillShort is _core_condition_still_holds: the core school's package
// for the year still short (or its assessment missing); a plan that cannot
// be found counts as still open.
func coreStillShort(ctx context.Context, db schooldirectory.Querier, a action) (bool, error) {
	var ref string
	err := db.QueryRow(ctx, `SELECT COALESCE(school_id, '') FROM school WHERE id = $1`, a.school).Scan(&ref)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && ref == "") {
		return true, nil
	}
	if err != nil {
		return false, fmt.Errorf("actionsweep: the core school: %w", err)
	}
	var plan string
	var visitsTarget, trainingsTarget int
	var assessed bool
	err = db.QueryRow(ctx, `SELECT id, COALESCE(visits_target, 0), COALESCE(trainings_target, 0), COALESCE(assessment_completed, 0) <> 0
FROM core_plan WHERE school_id = $1 AND fy = $2 ORDER BY id LIMIT 1`, ref, a.fy).Scan(&plan, &visitsTarget, &trainingsTarget, &assessed)
	if errors.Is(err, pgx.ErrNoRows) {
		return true, nil
	}
	if err != nil {
		return false, fmt.Errorf("actionsweep: the core plan: %w", err)
	}
	if a.issue == "core_assessment_missing" {
		return !assessed, nil
	}
	rows, err := db.Query(ctx, `SELECT COALESCE(activity_type, ''), COALESCE(status, '') FROM core_activity_slot WHERE core_plan_id = $1`, plan)
	if err != nil {
		return false, fmt.Errorf("actionsweep: the core plan's slots: %w", err)
	}
	defer rows.Close()
	core := coreRules()
	visits, trainings := 0, 0
	for rows.Next() {
		var kind, status string
		if err := rows.Scan(&kind, &status); err != nil {
			return false, err
		}
		if !core.SlotTaken(status) {
			continue
		}
		switch kind {
		case "visit":
			visits++
		case "training":
			trainings++
		}
	}
	if err := rows.Err(); err != nil {
		return false, err
	}
	if visitsTarget == 0 {
		visitsTarget = 4
	}
	if trainingsTarget == 0 {
		trainingsTarget = 4
	}
	return !(visits >= visitsTarget && trainings >= trainingsTarget), nil
}

// interventionStillWeak is _intervention_still_weak: the area the action
// names (else the school's weakest) still in the band that raised it; a
// warning holds until the area is Strong.
func interventionStillWeak(ctx context.Context, db schooldirectory.Querier, a action) (bool, error) {
	var exists bool
	if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school WHERE id = $1)`, a.school).Scan(&exists); err != nil {
		return false, fmt.Errorf("actionsweep: the school: %w", err)
	}
	if !exists {
		return false, nil
	}
	area := ""
	for _, part := range strings.Split(a.key, "|") {
		if strings.HasPrefix(part, "area:") {
			area = part[5:]
			break
		}
	}
	ranked, err := activities.RankedInterventions(ctx, db, a.school, interventionLimit)
	if err != nil || len(ranked) == 0 {
		return false, err
	}
	score := ranked[0].Score
	if area != "" {
		found := false
		for _, r := range ranked {
			if r.Intervention == area {
				score, found = r.Score, true
				break
			}
		}
		if !found {
			return false, nil
		}
	}
	if a.issue == "intervention_warning" {
		return band(score) != "Strong", nil
	}
	return band(score) == "Critical", nil
}
