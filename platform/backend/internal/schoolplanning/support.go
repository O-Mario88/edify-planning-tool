package schoolplanning

import (
	"context"
	"fmt"
	"strconv"
	"time"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// PartnerSupported is, for each school, whether a partner holds its support
// in the year fy (SupportResponsibility.is_partner): a hand-over not given
// back to staff, still waiting for a date, or dated into fy or a later year
// on an activity neither deleted nor closed (active_assignment_q).
func PartnerSupported(ctx context.Context, q Querier, schoolIDs []string, fy string) (map[string]bool, error) {
	out := map[string]bool{}
	if len(schoolIDs) == 0 {
		return out, nil
	}
	rows, err := q.Query(ctx, `
SELECT DISTINCT pa.school_id FROM partner_assignment pa
LEFT JOIN activity a ON a.id = pa.scheduled_activity_id
WHERE pa.school_id = ANY($1) AND pa.school_id IS NOT NULL
  AND pa.status IS DISTINCT FROM 'returned_to_staff'
  AND (pa.scheduled_activity_id IS NULL
    OR (pa.scheduled_activity_id IS NOT NULL AND a.deleted_at IS NULL
      AND NOT COALESCE(a.status = ANY($2), false) AND a.fy >= $3))`,
		schoolIDs, rules.ClosedHandoverActivityStatuses, fy)
	if err != nil {
		return nil, fmt.Errorf("schoolplanning: reading partner support: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("schoolplanning: reading partner support: %w", err)
		}
		out[id] = true
	}
	return out, rows.Err()
}

// Next is a school's Next Activity: its words and day.
type Next struct {
	Label string
	Day   time.Time
}

// NextActivities is planning_support.next_activities: each school's
// earliest planned activity from today on (ties to the lower id), named by
// its type, or its badge, and "Partner …" where a partner delivers it.
func NextActivities(ctx context.Context, q Querier, counted []Counted, now time.Time) (map[string]Next, error) {
	l := now.In(Nairobi)
	today := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
	first := map[string]Counted{}
	for _, c := range counted {
		if c.Bucket != bucketPlanned || c.Day == nil || c.Day.Before(today) {
			continue
		}
		current, ok := first[c.SchoolID]
		if !ok || c.Day.Before(*current.Day) || (c.Day.Equal(*current.Day) && c.ActivityID < current.ActivityID) {
			first[c.SchoolID] = c
		}
	}
	out := map[string]Next{}
	if len(first) == 0 {
		return out, nil
	}
	ids := []string{}
	for _, c := range first {
		ids = append(ids, c.ActivityID)
	}
	partner := map[string]bool{}
	rows, err := q.Query(ctx, `SELECT id FROM activity WHERE id = ANY($1) AND delivery_type = 'partner' AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolplanning: reading partner delivery: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("schoolplanning: reading partner delivery: %w", err)
		}
		partner[id] = true
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for schoolID, c := range first {
		noun := rules.NextNouns[c.ActivityType]
		if noun == "" {
			noun = rules.KindNouns[c.Kind]
		}
		if partner[c.ActivityID] {
			noun = "Partner " + noun
		}
		out[schoolID] = Next{Label: noun, Day: *c.Day}
	}
	return out, nil
}

// Horizon is fy_policy.planning_horizon(fy): the page year alone, except
// the operational year, which reads forward through every later year the FY
// selector offers and any year opened for planning beyond it. The years
// opened are the request's country's (place, docs/migration/80 §13): Uganda's
// policy rows wherever its roles are the existing profile's.
func Horizon(ctx context.Context, q Querier, place *registry.Work, fy string, operational int, fyOptions []string, now time.Time) ([]string, error) {
	if fy != strconv.Itoa(operational) {
		return []string{fy}, nil
	}
	latest := operational
	for _, y := range fyOptions {
		if n, err := strconv.Atoi(y); err == nil && n > latest {
			latest = n
		}
	}
	rows, err := q.Query(ctx, `
SELECT fy FROM fiscal_year_planning_policy WHERE country = $1 AND planning_open_at <= $2 ORDER BY fy`,
		registry.SettingsName(place, rules.DefaultCountry), now)
	if err != nil {
		return nil, fmt.Errorf("schoolplanning: reading the planning calendar: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var year string
		if err := rows.Scan(&year); err != nil {
			return nil, fmt.Errorf("schoolplanning: reading the planning calendar: %w", err)
		}
		if n, err := strconv.Atoi(year); err == nil && n > operational && n > latest {
			latest = n
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	out := []string{}
	for y := operational; y <= latest; y++ {
		out = append(out, strconv.Itoa(y))
	}
	return out, nil
}
