// Package autopilotjobs is the autopilot_weekly_proposals job
// (apps.autopilot.services.generate_weekly_proposals_for_all): every Friday
// each active CCEO with a portfolio gets a draft of next week: their
// portfolio schools without support this month, SSA-outstanding first, then
// the weakest, grouped by sub-county into up to three visits a day on the
// days the calendar leaves them. An accepted week is final; a live draft is
// dismissed and drafted again. Inside the caller's transaction.
package autopilotjobs

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	maxSchoolsPerDay  = 3
	workableWeekdays  = 6 // Mon–Sat
	visitStableCode   = "STANDARD_SCHOOL_VISIT"
	visitActivityType = "school_visit"
)

// interventionLabels are SsaIntervention's labels.
var interventionLabels = map[string]string{
	"christlike_behaviour": "Christlike Behaviour", "exposure_to_word_of_god": "Exposure to the Word of God",
	"financial_health": "Financial Health", "leadership": "Leadership",
	"government_requirement": "Government Requirements", "learning_environment": "Learning Environment",
	"teaching_environment": "Teacher's Environment", "enrolment": "Enrolment",
}

// band is ssa_score_band's label.
func band(score float64) string {
	switch {
	case score >= 8:
		return "Strong"
	case score >= 6:
		return "Improving"
	case score >= 5:
		return "Warning"
	}
	return "Critical"
}

// pyG is f"{x:g}".
func pyG(x float64) string { return strconv.FormatFloat(x, 'g', 6, 64) }

// officer is one CCEO the job drafts for.
type officer struct {
	staffID, userID, name, role, country string
}

// WeeklyProposals is the job for next week in Kampala; it says how many
// drafts it made.
func WeeklyProposals(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, logger *slog.Logger) (int, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	weekStart := today.AddDate(0, 0, 7-((int(today.Weekday())+6)%7))
	rows, err := tx.Query(ctx, `SELECT DISTINCT sp.id, u.id, COALESCE(u.name, ''), COALESCE(u.active_role, ''), COALESCE(sp.country, '')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.status = 'active' AND 'CCEO' = ANY(u.roles)
  AND EXISTS (SELECT 1 FROM staff_school_assignment a WHERE a.staff_id = sp.id)`)
	if err != nil {
		return 0, fmt.Errorf("autopilotjobs: reading the officers: %w", err)
	}
	var officers []officer
	for rows.Next() {
		var o officer
		if err := rows.Scan(&o.staffID, &o.userID, &o.name, &o.role, &o.country); err != nil {
			rows.Close()
			return 0, err
		}
		officers = append(officers, o)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	generated := 0
	for _, o := range officers {
		if _, err := tx.Exec(ctx, `SAVEPOINT proposal`); err != nil {
			return generated, err
		}
		made, err := weekProposal(ctx, tx, o, weekStart, today, now, kampala)
		if err != nil {
			// One person never blocks the roster.
			if _, rbErr := tx.Exec(ctx, `ROLLBACK TO SAVEPOINT proposal`); rbErr != nil {
				return generated, rbErr
			}
			if logger != nil {
				logger.WarnContext(ctx, "autopilotjobs: weekly proposal generation failed", "staff", o.staffID, "err", err)
			}
			continue
		}
		if _, err := tx.Exec(ctx, `RELEASE SAVEPOINT proposal`); err != nil {
			return generated, err
		}
		if made {
			generated++
		}
	}
	return generated, nil
}

// weekProposal is generate_week_proposal; false for an accepted week.
func weekProposal(ctx context.Context, tx pgx.Tx, o officer, weekStart, today, now time.Time, kampala *time.Location) (bool, error) {
	var existingID, status string
	err := tx.QueryRow(ctx, `SELECT id, status FROM autopilot_proposed_plan WHERE staff_id = $1 AND week_start = $2
ORDER BY id LIMIT 1`, o.staffID, weekStart.Format(time.DateOnly)).Scan(&existingID, &status)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("autopilotjobs: reading the week's draft: %w", err)
	}
	if status == "accepted" {
		return false, nil
	}
	if status == "proposed" {
		if _, err := tx.Exec(ctx, `UPDATE autopilot_proposed_plan SET status = 'dismissed', updated_at = $2 WHERE id = $1`,
			existingID, now); err != nil {
			return false, fmt.Errorf("autopilotjobs: dismissing the old draft: %w", err)
		}
	}
	days, err := workableDays(ctx, tx, o, weekStart)
	if err != nil {
		return false, err
	}
	candidates, err := candidateSchools(ctx, tx, o, maxSchoolsPerDay*max(len(days), 1), today, now, kampala)
	if err != nil {
		return false, err
	}
	dayList := make([]string, 0, len(days))
	for _, d := range days {
		dayList = append(dayList, d.Format(time.DateOnly))
	}
	planID := cuid.New()
	if _, err := tx.Exec(ctx, `INSERT INTO autopilot_proposed_plan (id, created_at, updated_at, staff_id, week_start, status,
  rationale, accepted_by, accepted_at)
VALUES ($1, $2, $2, $3, $4, 'proposed', $5, '', NULL)`, planID, now, o.staffID, weekStart.Format(time.DateOnly),
		map[string]any{
			"workableDays": dayList, "candidatesConsidered": len(candidates),
			"ordering": "SSA-outstanding first, then coverage gaps", "grouping": "sub-county route days",
			"maxSchoolsPerDay": maxSchoolsPerDay,
		}); err != nil {
		return false, fmt.Errorf("autopilotjobs: recording the draft: %w", err)
	}
	type group struct {
		area string
		rows []candidate
	}
	var groups []*group
	index := map[string]*group{}
	for _, c := range candidates {
		area := c.area
		if area == "" {
			area = "Unlocated"
		}
		g, ok := index[area]
		if !ok {
			g = &group{area: area}
			index[area] = g
			groups = append(groups, g)
		}
		g.rows = append(g.rows, c)
	}
	sort.SliceStable(groups, func(i, j int) bool { return len(groups[i].rows) > len(groups[j].rows) })
	dayIndex := 0
	for _, g := range groups {
		for start := 0; start < len(g.rows); start += maxSchoolsPerDay {
			if dayIndex >= len(days) {
				break
			}
			for _, c := range g.rows[start:min(start+maxSchoolsPerDay, len(g.rows))] {
				if _, err := tx.Exec(ctx, `INSERT INTO autopilot_proposed_activity (id, created_at, updated_at, plan_id, school_id,
  school_name, area, proposed_date, activity_type, catalogue_stable_code, reason, created_activity_id)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, '')`, cuid.New(), now, planID, c.id, c.name, g.area,
					days[dayIndex].Format(time.DateOnly), visitActivityType, visitStableCode, c.reason); err != nil {
					return false, fmt.Errorf("autopilotjobs: recording a proposed visit: %w", err)
				}
			}
			dayIndex++
		}
		if dayIndex >= len(days) {
			break
		}
	}
	return true, nil
}

// workableDays is _workable_days: Monday to Saturday of the week, less every
// day the calendar check finds a conflict on (SchedulingPolicyService.check's
// calendarConflicts: a public holiday, a blackout, a staff conference or an
// event reaching the person, or their approved leave).
func workableDays(ctx context.Context, tx pgx.Tx, o officer, weekStart time.Time) ([]time.Time, error) {
	end := weekStart.AddDate(0, 0, workableWeekdays-1)
	holidays, err := calendarpage.PublicHolidayDays(ctx, tx, weekStart, end)
	if err != nil {
		return nil, err
	}
	var out []time.Time
	for i := 0; i < workableWeekdays; i++ {
		d := weekStart.AddDate(0, 0, i)
		if d.Weekday() == time.Sunday || holidays[d.Format(time.DateOnly)] {
			continue
		}
		blocked, err := calendarBlocked(ctx, tx, o, d)
		if err != nil {
			return nil, err
		}
		if !blocked {
			out = append(out, d)
		}
	}
	return out, nil
}

func calendarBlocked(ctx context.Context, tx pgx.Tx, o officer, d time.Time) (bool, error) {
	day := d.Format(time.DateOnly)
	rows, err := tx.Query(ctx, `SELECT block_type, COALESCE(applies_to_roles, '[]'::jsonb), applies_to_all_roles, COALESCE(country, ''),
  COALESCE(region_id, ''), COALESCE(district_id, '')
FROM calendar_block WHERE is_active AND start_date <= $1 AND end_date >= $1`, day)
	if err != nil {
		return false, fmt.Errorf("autopilotjobs: reading the calendar: %w", err)
	}
	type block struct {
		kind                      string
		roles                     []string
		allRoles                  bool
		country, region, district string
	}
	var blocks []block
	for rows.Next() {
		var b block
		var roles []byte
		if err := rows.Scan(&b.kind, &roles, &b.allRoles, &b.country, &b.region, &b.district); err != nil {
			rows.Close()
			return false, err
		}
		var list []any
		if json.Unmarshal(roles, &list) == nil {
			for _, r := range list {
				if s, ok := r.(string); ok {
					b.roles = append(b.roles, s)
				}
			}
		}
		blocks = append(blocks, b)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return false, err
	}
	for _, b := range blocks {
		switch b.kind {
		case "PUBLIC_HOLIDAY", "BLACKOUT_DATE":
			return true, nil
		case "STAFF_CONFERENCE":
			restricted := len(b.roles) > 0 && !slices.Contains(b.roles, o.role)
			if b.allRoles || restricted {
				return true, nil
			}
		case "REGIONAL_EVENT", "ORG_EVENT", "CUSTOM_BLOCK":
			reached := true
			if b.country != "" && o.country != "" && o.country != b.country {
				reached = false
			}
			for _, geo := range []struct{ col, id string }{{"region_id", b.region}, {"district_id", b.district}} {
				if geo.id == "" {
					continue
				}
				var assigned bool
				if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM staff_geography_assignment WHERE staff_id = $1 AND `+
					geo.col+` = $2)`, o.staffID, geo.id).Scan(&assigned); err != nil {
					return false, fmt.Errorf("autopilotjobs: reading the officer's geography: %w", err)
				}
				if !assigned {
					reached = false
				}
			}
			if reached {
				return true, nil
			}
		}
	}
	var onLeave bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM leave WHERE staff_id = $1 AND status = 'approved'
  AND start_date <= $2 AND end_date >= $2)`, o.staffID, day).Scan(&onLeave); err != nil {
		return false, fmt.Errorf("autopilotjobs: reading the officer's leave: %w", err)
	}
	return onLeave, nil
}

// candidate is one portfolio school the draft may visit.
type candidate struct {
	id, name, area, reason string
	outstanding            bool
	urgency                float64
}

// candidateSchools is _candidate_schools.
func candidateSchools(ctx context.Context, tx pgx.Tx, o officer, limit int, today, now time.Time,
	kampala *time.Location) ([]candidate, error) {
	monthStart := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC).Format(time.DateOnly)
	fy := schooldirectory.OperationalFY(now.In(kampala))
	rows, err := tx.Query(ctx, `
WITH portfolio AS (SELECT school_id FROM staff_school_assignment WHERE staff_id = $1),
covered AS (SELECT school_id FROM activity WHERE school_id IN (SELECT school_id FROM portfolio) AND planned_date >= $2
  AND deleted_at IS NULL AND status NOT IN ('cancelled', 'rejected')),
visited AS (SELECT school_id FROM activity WHERE school_id IN (SELECT school_id FROM portfolio) AND fy = $3
  AND activity_type = 'school_visit' AND deleted_at IS NULL AND status NOT IN ('cancelled', 'rejected'))
SELECT s.id, s.name, COALESCE(sc.name, ''), COALESCE(s.current_fy_ssa_status, '') <> 'done'
FROM school s LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
WHERE s.id IN (SELECT school_id FROM portfolio) AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
  AND s.id NOT IN (SELECT school_id FROM covered WHERE school_id IS NOT NULL)
  AND NOT (s.id IN (SELECT school_id FROM visited WHERE school_id IS NOT NULL) AND s.school_type IN ('client', 'core_trained'))
ORDER BY s.name LIMIT $4`, o.staffID, monthStart, fy, limit*2)
	if err != nil {
		return nil, fmt.Errorf("autopilotjobs: reading the candidate schools: %w", err)
	}
	var out []candidate
	var ids []string
	for rows.Next() {
		var c candidate
		if err := rows.Scan(&c.id, &c.name, &c.area, &c.outstanding); err != nil {
			rows.Close()
			return nil, err
		}
		out = append(out, c)
		ids = append(ids, c.id)
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(out) == 0 {
		return out, err
	}
	latest, err := latestRecords(ctx, tx, ids)
	if err != nil {
		return nil, err
	}
	for i := range out {
		c := &out[i]
		rec := latest[c.id]
		need := ""
		if rec != nil && rec.weakest != nil {
			label := interventionLabels[rec.weakest.code]
			if label == "" {
				label = rec.weakest.code
			}
			need = fmt.Sprintf("%s %s/10 (%s)", label, pyG(rec.weakest.score), band(rec.weakest.score))
		}
		switch {
		case c.outstanding:
			c.reason = "SSA outstanding this FY: collect the assessment"
			if need != "" {
				c.reason += "; last need " + need
			}
		case need != "":
			c.reason = "SSA need: " + need
		default:
			c.reason = "No support activity this month"
		}
		c.reason = firstRunes(c.reason, 255)
		c.urgency = 99.0
		if rec != nil && rec.average != nil {
			c.urgency = *rec.average
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.outstanding != b.outstanding {
			return a.outstanding
		}
		if a.urgency != b.urgency {
			return a.urgency < b.urgency
		}
		return a.name < b.name
	})
	if len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

type weakest struct {
	code  string
	score float64
}

type latestRecord struct {
	average *float64
	weakest *weakest
}

// latestRecords is latest_applicable_records and bulk_weakest(n=1): each
// school's latest confirmed assessment, its average and its lowest score
// (ties on the intervention key).
func latestRecords(ctx context.Context, tx pgx.Tx, schools []string) (map[string]*latestRecord, error) {
	rows, err := tx.Query(ctx, `SELECT DISTINCT ON (r.school_id) r.school_id, r.average_score,
  (SELECT s.intervention FROM ssa_score s WHERE s.ssa_record_id = r.id AND s.score IS NOT NULL ORDER BY s.score, s.intervention LIMIT 1),
  (SELECT s.score FROM ssa_score s WHERE s.ssa_record_id = r.id AND s.score IS NOT NULL ORDER BY s.score, s.intervention LIMIT 1)
FROM ssa_record r WHERE r.school_id = ANY($1) AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'
ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC`, schools)
	if err != nil {
		return nil, fmt.Errorf("autopilotjobs: reading the schools' assessments: %w", err)
	}
	defer rows.Close()
	out := map[string]*latestRecord{}
	for rows.Next() {
		var school string
		var code *string
		var score *float64
		rec := &latestRecord{}
		if err := rows.Scan(&school, &rec.average, &code, &score); err != nil {
			return nil, err
		}
		if code != nil && score != nil {
			rec.weakest = &weakest{code: *code, score: *score}
		}
		out[school] = rec
	}
	return out, rows.Err()
}

func firstRunes(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}
