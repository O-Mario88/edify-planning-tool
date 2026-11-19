package partneroversight

import (
	"context"
	"fmt"
	"math"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// followUps is partner_follow_up.partners_needing_follow_up: {partner id:
// recommendation} for each Partner whose Country Director Analytics
// recommendation for fy is one to follow up (CDAnalyticsService.
// partner_performance over resolve_cd_scope(fy, country)). country is the
// reader's scope's country, "" for the whole deployment.
func followUps(ctx context.Context, db schooldirectory.Querier, country, fy string) (map[string]string, error) {
	f := rules.Work.FollowUp
	// _cycle_fys over the country's operating schools: the latest two years
	// with a confirmed SSA, up to fy.
	rows, err := db.Query(ctx, `
SELECT DISTINCT r.fy FROM ssa_record r JOIN school s ON s.id = r.school_id
LEFT JOIN region rg ON rg.id = s.region_id
WHERE r.deleted_at IS NULL AND r.verification_status = 'confirmed' AND r.fy <= $1
  AND s.deleted_at IS NULL AND s.operational_status = ANY($2) AND ($3 = '' OR rg.country = $3)
ORDER BY r.fy DESC LIMIT 2`, fy, f.OperatingStatuses, country)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the SSA cycles: %w", err)
	}
	cycles := []string{}
	for rows.Next() {
		var y string
		if err := rows.Scan(&y); err != nil {
			rows.Close()
			return nil, fmt.Errorf("partneroversight: reading the SSA cycles: %w", err)
		}
		cycles = append(cycles, y)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	out := map[string]string{}
	if len(cycles) < 2 {
		// No SSA movement can be measured: every recommendation is
		// Insufficient Data, none followed up.
		return out, nil
	}
	latest, prev := cycles[0], cycles[1]

	// Each Partner's planned and done work in the year, its schools (not
	// released), and their confirmed SSA means in the two cycles.
	rows, err = db.Query(ctx, `
WITH partners AS (SELECT id FROM partner WHERE deleted_at IS NULL),
counts AS (
  SELECT a.assigned_partner_id AS id, count(*) AS planned, count(*) FILTER (WHERE a.status = ANY($2)) AS done
  FROM activity a
  LEFT JOIN school s ON s.id = a.school_id LEFT JOIN region rg ON rg.id = s.region_id
  LEFT JOIN cluster c ON c.id = a.cluster_id LEFT JOIN district cd ON cd.id = c.district_id
  LEFT JOIN region crg ON crg.id = cd.region_id
  WHERE a.fy = $1 AND a.deleted_at IS NULL AND NOT (a.status = ANY($3)) AND a.assigned_partner_id IN (SELECT id FROM partners)
    AND ($4 = '' OR rg.country = $4 OR crg.country = $4
      OR (a.school_id IS NULL AND a.cluster_id IS NULL
        AND a.responsible_staff_id IN (SELECT id FROM staff_profile WHERE country = $4)))
  GROUP BY a.assigned_partner_id),
schools AS (
  SELECT DISTINCT pa.partner_id AS id, pa.school_id FROM partner_assignment pa
  WHERE pa.partner_id IN (SELECT id FROM partners) AND pa.school_id IS NOT NULL AND NOT (pa.status = ANY($5))),
ssa AS (
  SELECT sc.id, avg(r.average_score::float8) FILTER (WHERE r.fy = $6) AS cur,
    avg(r.average_score::float8) FILTER (WHERE r.fy = $7) AS old,
    count(*) FILTER (WHERE r.fy = $6) AS cur_n, count(*) FILTER (WHERE r.fy = $7) AS old_n
  FROM schools sc JOIN ssa_record r ON r.school_id = sc.school_id
  WHERE r.deleted_at IS NULL AND r.verification_status = 'confirmed' AND r.fy IN ($6, $7) AND r.average_score IS NOT NULL
  GROUP BY sc.id)
SELECT p.id, COALESCE(c.planned, 0), COALESCE(c.done, 0), s.cur, s.old, COALESCE(s.cur_n, 0), COALESCE(s.old_n, 0)
FROM partners p LEFT JOIN counts c ON c.id = p.id LEFT JOIN ssa s ON s.id = p.id`,
		fy, f.Completed, f.NotInPlan, country, f.Released, latest, prev)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the Partners' performance: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var planned, done, curN, oldN int
		var cur, old *float64
		if err := rows.Scan(&id, &planned, &done, &cur, &old, &curN, &oldN); err != nil {
			return nil, fmt.Errorf("partneroversight: reading the Partners' performance: %w", err)
		}
		var improve *float64
		if cur != nil && old != nil && curN > 0 && oldN > 0 {
			v := schooldirectory.PyRound1(*cur - *old)
			improve = &v
		}
		if rec := recommendation(percentOrZero(done, planned), improve, planned); in(f.Recommendations, rec) {
			out[id] = rec
		}
	}
	return out, rows.Err()
}

// percentOrZero is percentage_or_zero: a whole percentage, rounded half to
// even as Python's round, 0 of nothing.
func percentOrZero(n, d int) int {
	if d == 0 {
		return 0
	}
	return int(math.RoundToEven(float64(n) / float64(d) * 100))
}

// recommendation is CDAnalyticsService._partner_recommendation's words.
func recommendation(targetPct int, improve *float64, planned int) string {
	switch {
	case planned == 0, improve == nil:
		return "Insufficient Data"
	case *improve < 0:
		return "Drop / Do Not Renew"
	case targetPct >= 70 && *improve >= 0.5:
		return "Assign More Schools"
	case targetPct >= 70:
		return "Quality Review"
	case targetPct < 55 && *improve >= 0.5:
		return "Capacity Review"
	case targetPct < 55:
		return "Drop / Replace"
	}
	return "Keep Active"
}

// FollowUps is partner_follow_up.partners_needing_follow_up for country and
// fy: {partner id: recommendation} for each Partner the Country Director
// Analytics would have followed up (CDAnalyticsService.recommended_actions
// counts them).
func FollowUps(ctx context.Context, db schooldirectory.Querier, country, fy string) (map[string]string, error) {
	return followUps(ctx, db, country, fy)
}
