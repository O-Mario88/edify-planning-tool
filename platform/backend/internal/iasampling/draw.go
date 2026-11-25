// Package iasampling is the verification_sampling job
// (apps.activities.verification_sampling.draw_samples): each week a share of
// the activities verified and the SSA records confirmed in the last seven
// days, never sampled before, is drawn per country for a second look. The
// draw is seeded by the day and the country, as the existing one is, so it
// picks the same work; one draw per country per day.
package iasampling

import (
	"context"
	"fmt"
	"math"
	"slices"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pyrandom"
)

const (
	// sharePct is DEFAULT_SHARE_PCT; IA_VERIFICATION_SAMPLE_SHARE_PCT is set
	// nowhere in the existing settings.
	sharePct   = 10
	windowDays = 7
	system     = "system"
)

type history struct{ activityID, verifiedBy string }
type record struct{ id, verifier string }

type frame struct {
	activities []history
	ssa        []record
}

// Draw is draw_samples(days=7) for every country; it says how many samples
// it made.
func Draw(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location) (int, error) {
	since := now.AddDate(0, 0, -windowDays)
	histories, err := readHistories(ctx, tx, since)
	if err != nil {
		return 0, err
	}
	countries, err := activityCountries(ctx, tx, histories)
	if err != nil {
		return 0, err
	}
	records, err := readRecords(ctx, tx, since)
	if err != nil {
		return 0, err
	}
	frames := map[string]*frame{}
	at := func(place string) *frame {
		if frames[place] == nil {
			frames[place] = &frame{}
		}
		return frames[place]
	}
	for _, h := range histories {
		f := at(countries[h.activityID])
		f.activities = append(f.activities, h)
	}
	for _, r := range records {
		f := at(r.place)
		f.ssa = append(f.ssa, record{id: r.id, verifier: r.verifier})
	}
	places := make([]string, 0, len(frames))
	for place := range frames {
		places = append(places, place)
	}
	sort.Strings(places)
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, kampala)
	created := 0
	for _, place := range places {
		n, err := drawCountry(ctx, tx, place, frames[place], today, now)
		if err != nil {
			return created, err
		}
		created += n
	}
	return created, nil
}

// readHistories is the week's verification history not yet sampled, one row
// per activity (its first), by verification time.
func readHistories(ctx context.Context, tx pgx.Tx, since time.Time) ([]history, error) {
	rows, err := tx.Query(ctx, `SELECT h.activity_id, h.verified_by FROM ia_verification_history h
WHERE h.verified_at >= $1 AND NOT EXISTS (SELECT 1 FROM ia_verification_sample s
  WHERE s.activity_id IS NOT NULL AND s.activity_id = h.activity_id)
ORDER BY h.verified_at, h.id`, since)
	if err != nil {
		return nil, fmt.Errorf("iasampling: reading the week's verifications: %w", err)
	}
	all, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (history, error) {
		var h history
		err := row.Scan(&h.activityID, &h.verifiedBy)
		return h, err
	})
	if err != nil {
		return nil, fmt.Errorf("iasampling: reading the week's verifications: %w", err)
	}
	var out []history
	seen := map[string]bool{}
	for _, h := range all {
		if !seen[h.activityID] {
			seen[h.activityID] = true
			out = append(out, h)
		}
	}
	return out, nil
}

// activityCountries is _activity_countries: the school's or cluster's
// region's country, else the responsible person's profile's.
func activityCountries(ctx context.Context, tx pgx.Tx, histories []history) (map[string]string, error) {
	out := map[string]string{}
	if len(histories) == 0 {
		return out, nil
	}
	ids := make([]string, 0, len(histories))
	for _, h := range histories {
		ids = append(ids, h.activityID)
	}
	rows, err := tx.Query(ctx, `SELECT a.id, COALESCE(NULLIF(sr.country, ''), NULLIF(cr.country, ''),
  (SELECT COALESCE(sp.country, '') FROM staff_profile sp WHERE sp.id = a.responsible_staff_id OR sp.user_id = a.responsible_staff_id
   ORDER BY sp.id LIMIT 1), '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN region sr ON sr.id = s.region_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN region cr ON cr.id = cl.region_id
WHERE a.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("iasampling: reading where the work was: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, country string
		if err := rows.Scan(&id, &country); err != nil {
			return nil, err
		}
		out[id] = country
	}
	return out, rows.Err()
}

type placedRecord struct{ id, verifier, place string }

func readRecords(ctx context.Context, tx pgx.Tx, since time.Time) ([]placedRecord, error) {
	rows, err := tx.Query(ctx, `SELECT r.id, r.verified_by_user_id, COALESCE(rg.country, '') FROM ssa_record r
LEFT JOIN school s ON s.id = r.school_id LEFT JOIN region rg ON rg.id = s.region_id
WHERE r.verification_status = 'confirmed' AND r.deleted_at IS NULL AND r.verified_at >= $1
  AND r.verified_by_user_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM ia_verification_sample x WHERE x.ssa_record_id IS NOT NULL AND x.ssa_record_id = r.id)
ORDER BY r.verified_at, r.id`, since)
	if err != nil {
		return nil, fmt.Errorf("iasampling: reading the week's confirmed SSA records: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (placedRecord, error) {
		var r placedRecord
		err := row.Scan(&r.id, &r.verifier, &r.place)
		return r, err
	})
}

// drawnToday is _draw_country's once-a-day check for the place.
func drawnToday(ctx context.Context, tx pgx.Tx, place string, today time.Time) (bool, error) {
	day := `s.sampled_at >= $1 AND s.sampled_at < $2`
	args := []any{today, today.AddDate(0, 0, 1)}
	var where string
	if place != "" {
		args = append(args, place)
		where = day + ` AND (sr.country = $3 OR cr.country = $3
  OR (a.school_id IS NULL AND a.cluster_id IS NULL AND a.responsible_staff_id IN (SELECT sp.id FROM staff_profile sp WHERE sp.country = $3))
  OR xr.country = $3)`
	} else {
		where = day + ` AND NOT (s2.region_id IS NOT NULL OR cl.region_id IS NOT NULL OR s.ssa_record_id IS NOT NULL)`
	}
	var drawn bool
	err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM ia_verification_sample s
  LEFT JOIN activity a ON a.id = s.activity_id
  LEFT JOIN school s2 ON s2.id = a.school_id LEFT JOIN region sr ON sr.id = s2.region_id
  LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN region cr ON cr.id = cl.region_id
  LEFT JOIN ssa_record x ON x.id = s.ssa_record_id LEFT JOIN school xs ON xs.id = x.school_id
  LEFT JOIN region xr ON xr.id = xs.region_id
  WHERE `+where+`)`, args...).Scan(&drawn)
	if err != nil {
		return false, fmt.Errorf("iasampling: reading today's draw: %w", err)
	}
	return drawn, nil
}

// take is max(1, ceil(len * share / 100)), at most everything.
func take(count int) int {
	return min(count, max(1, int(math.Ceil(float64(count)*sharePct/100))))
}

func drawCountry(ctx context.Context, tx pgx.Tx, place string, f *frame, today, now time.Time) (int, error) {
	if drawn, err := drawnToday(ctx, tx, place, today); err != nil || drawn {
		return 0, err
	}
	rng := pyrandom.New(today.Format(time.DateOnly) + ":" + place)
	created := 0
	if len(f.activities) > 0 {
		for _, i := range rng.Sample(len(f.activities), take(len(f.activities))) {
			h := f.activities[i]
			made, err := addSample(ctx, tx, "activity_id", h.activityID, "activity", h.verifiedBy, now)
			if err != nil {
				return created, err
			}
			created += made
		}
	}
	if len(f.ssa) > 0 {
		for _, i := range rng.Sample(len(f.ssa), take(len(f.ssa))) {
			r := f.ssa[i]
			made, err := addSample(ctx, tx, "ssa_record_id", r.id, "ssa_record", r.verifier, now)
			if err != nil {
				return created, err
			}
			created += made
		}
	}
	return created, nil
}

// addSample is get_or_create on the subject.
func addSample(ctx context.Context, tx pgx.Tx, column, subjectID, subjectType, verifier string, now time.Time) (int, error) {
	if !slices.Contains([]string{"activity_id", "ssa_record_id"}, column) {
		return 0, fmt.Errorf("iasampling: no sample subject %q", column)
	}
	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM ia_verification_sample WHERE `+column+` = $1 AND subject_type = $2)`,
		subjectID, subjectType).Scan(&exists); err != nil {
		return 0, fmt.Errorf("iasampling: reading the subject's sample: %w", err)
	}
	if exists {
		return 0, nil
	}
	if _, err := tx.Exec(ctx, `INSERT INTO ia_verification_sample (created_at, updated_at, id, original_verifier, sampled_at,
  sampled_by, status, outcome_note, `+column+`, method, subject_type)
VALUES ($1, $1, $2, $3, $1, $4, 'pending', '', $5, 'desk', $6)`, now, cuid.New(), verifier, system, subjectID, subjectType); err != nil {
		return 0, fmt.Errorf("iasampling: recording the sample: %w", err)
	}
	return 1, nil
}
