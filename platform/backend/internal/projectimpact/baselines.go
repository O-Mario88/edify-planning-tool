package projectimpact

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// pendingBaseline is an enrolment with no baseline and an intervention.
type pendingBaseline struct {
	id, intervention, classification string
	start                            time.Time
}

// CaptureBaselines is the `projects.baselines.capture` handler for one
// school: the empty baselines a confirmed reading dated on or before the
// enrolment's start supports are filled, and when one is, the school's
// impact is refreshed. It says how many it filled.
func CaptureBaselines(ctx context.Context, tx pgx.Tx, schoolID string, kampala *time.Location, now time.Time) (int, error) {
	pending, err := pendingBaselines(ctx, tx, schoolID, kampala)
	if err != nil || len(pending) == 0 {
		return 0, err
	}
	readings, err := capturableReadings(ctx, tx, schoolID, pending, kampala)
	if err != nil {
		return 0, err
	}
	filled := 0
	for _, p := range pending {
		found := qualifying(readings[p.intervention], p.start)
		if found == nil {
			continue
		}
		classification := p.classification
		if classification == "" || classification == insufficient {
			classification = notYetMeasurable
		}
		// Under the write: a baseline captured meanwhile is never overwritten.
		tag, err := tx.Exec(ctx, `UPDATE project_school_assignment SET baseline_ssa_id = $2, baseline_score = $3,
  baseline_band = $4, baseline_captured_at = $5, impact_classification = $6, updated_at = $5
WHERE id = $1 AND baseline_score IS NULL`, p.id, found.recordID, found.score, scoreBand(found.score), now, classification)
		if err != nil {
			return 0, fmt.Errorf("projectimpact: capturing a baseline: %w", err)
		}
		filled += int(tag.RowsAffected())
	}
	if filled > 0 {
		if _, err := RefreshSchoolImpact(ctx, tx, schoolID, kampala, now); err != nil {
			return 0, err
		}
	}
	return filled, nil
}

// pendingBaselines are _assignments for the school with an intervention,
// locked as the capture's re-check locks them.
func pendingBaselines(ctx context.Context, tx pgx.Tx, schoolID string, kampala *time.Location) ([]pendingBaseline, error) {
	rows, err := tx.Query(ctx, `
SELECT a.id, COALESCE(NULLIF(a.matched_intervention, ''), p.intervention, ''), a.impact_classification, a.start_date, a.created_at
FROM project_school_assignment a JOIN project p ON p.id = a.project_id
WHERE a.school_id = $1 AND a.baseline_score IS NULL AND p.deleted_at IS NULL
ORDER BY a.id
FOR UPDATE OF a`, schoolID)
	if err != nil {
		return nil, fmt.Errorf("projectimpact: reading the empty baselines: %w", err)
	}
	defer rows.Close()
	var out []pendingBaseline
	for rows.Next() {
		var p pendingBaseline
		var start *time.Time
		var created time.Time
		if err := rows.Scan(&p.id, &p.intervention, &p.classification, &start, &created); err != nil {
			return nil, err
		}
		if p.intervention == "" {
			continue
		}
		if start != nil {
			p.start = dayOf(*start)
		} else {
			p.start = dayOf(created.In(kampala))
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// capturableReadings are _readings_by_school for one school: confirmed, not
// deleted readings on the enrolments' interventions, oldest first, each on
// its Kampala day.
func capturableReadings(ctx context.Context, tx pgx.Tx, schoolID string, pending []pendingBaseline,
	kampala *time.Location) (map[string][]reading, error) {
	interventions := make([]string, 0, len(pending))
	for _, p := range pending {
		interventions = append(interventions, p.intervention)
	}
	rows, err := tx.Query(ctx, `SELECT s.intervention, r.date_of_ssa, s.score, s.ssa_record_id
FROM ssa_score s JOIN ssa_record r ON r.id = s.ssa_record_id
WHERE r.school_id = $1 AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL AND s.intervention = ANY($2)
ORDER BY r.date_of_ssa, s.ssa_record_id`, schoolID, interventions)
	if err != nil {
		return nil, fmt.Errorf("projectimpact: reading the school's assessments: %w", err)
	}
	defer rows.Close()
	out := map[string][]reading{}
	for rows.Next() {
		var code string
		var on *time.Time
		var rd reading
		if err := rows.Scan(&code, &on, &rd.score, &rd.recordID); err != nil {
			return nil, err
		}
		if on == nil || rd.score < scoreMin || rd.score > scoreMax {
			continue
		}
		rd.on = dayOf(on.In(kampala))
		out[code] = append(out[code], rd)
	}
	return out, rows.Err()
}

// qualifying is _qualifying: the latest reading dated on or before the start.
func qualifying(readings []reading, start time.Time) *reading {
	var found *reading
	for i := range readings {
		if readings[i].on.After(start) {
			break
		}
		found = &readings[i]
	}
	return found
}
