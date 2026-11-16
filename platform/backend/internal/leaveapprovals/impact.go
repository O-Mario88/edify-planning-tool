package leaveapprovals

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// blackoutCountry is get_blackout_dates_in_range's default country.
const blackoutCountry = "Uganda"

// coverWorkload is "cover_acts_count > 5": a cover this busy is a warning.
const coverWorkload = 5

// liveWork is the activity statuses impact analysis counts as still due.
var liveWork = []string{"planned", "scheduled", "rescheduled", "partner_scheduled", "in_progress"}

// conflict is one of LeaveConflictDetectionService.detect's findings.
type conflict struct {
	kind, action, dates string
	critical            bool
}

func parseDay(s string) (time.Time, bool) {
	t, err := time.Parse(time.DateOnly, s)
	return t, err == nil
}

// window is scheduled_datetime_window: the leave's first day's midnight to
// the midnight after its last, in the project's zone.
func window(start, end time.Time) (time.Time, time.Time) {
	return time.Date(start.Year(), start.Month(), start.Day(), 0, 0, 0, 0, zone),
		time.Date(end.Year(), end.Month(), end.Day()+1, 0, 0, 0, 0, zone)
}

func ownerIDs(ctx context.Context, db schooldirectory.Querier, staff string) ([]string, error) {
	var user *string
	if err := db.QueryRow(ctx, `SELECT user_id FROM staff_profile WHERE id = $1`, staff).Scan(&user); err != nil && err != pgx.ErrNoRows {
		return nil, fmt.Errorf("leaveapprovals: reading a People record: %w", err)
	}
	ids := []string{staff}
	if user != nil {
		ids = append(ids, *user)
	}
	return ids, nil
}

// detect is LeaveConflictDetectionService.detect, in its order: work booked
// in the leave, public holidays, blackout days, staff conferences, the
// cover's own leave and the cover's workload. full=false stops at the
// critical findings the queue's count needs.
func detect(ctx context.Context, db schooldirectory.Querier, l leave, full bool) ([]conflict, error) {
	s, ok1 := parseDay(l.start)
	e, ok2 := parseDay(l.end)
	if !ok1 || !ok2 {
		return nil, fmt.Errorf("leaveapprovals: leave %s has unreadable dates", l.id)
	}
	from, to := window(s, e)
	owners, err := ownerIDs(ctx, db, l.staffID)
	if err != nil {
		return nil, err
	}
	out := []conflict{}
	rows, err := db.Query(ctx, `SELECT scheduled_date FROM activity WHERE deleted_at IS NULL AND responsible_staff_id = ANY($1)
  AND scheduled_date >= $2 AND scheduled_date < $3 AND NOT (status IN ('cancelled', 'completed'))`, owners, from, to)
	if err != nil {
		return nil, fmt.Errorf("leaveapprovals: reading the work booked in a leave: %w", err)
	}
	booked, err := pgx.CollectRows(rows, pgx.RowTo[*time.Time])
	if err != nil {
		return nil, fmt.Errorf("leaveapprovals: reading the work booked in a leave: %w", err)
	}
	for _, at := range booked {
		day := ""
		if at != nil {
			day = at.In(zone).Format(time.DateOnly)
		}
		out = append(out, conflict{kind: "activity_during_leave", action: "Reschedule or Reassign this activity.", dates: day, critical: true})
	}
	if full {
		days, err := calendarpage.PublicHolidayDays(ctx, db, s, e)
		if err != nil {
			return nil, err
		}
		sorted := []string{}
		for d := range days {
			sorted = append(sorted, d)
		}
		sort.Strings(sorted)
		for _, d := range sorted {
			out = append(out, conflict{kind: "public_holiday", action: "Leave request overlaps with a public holiday.", dates: d})
		}
	}
	blocked, err := blackoutDays(ctx, db, s, e)
	if err != nil {
		return nil, err
	}
	for _, d := range blocked {
		out = append(out, conflict{kind: "blackout_date", action: "Requested period includes a blocked organizational date.", dates: d, critical: true})
	}
	if full {
		rows, err := db.Query(ctx, `SELECT start_date::text, end_date::text, COALESCE(title, '') FROM calendar_block
WHERE block_type = 'STAFF_CONFERENCE' AND is_active AND start_date <= $1::date AND end_date >= $2::date`, l.end, l.start)
		if err != nil {
			return nil, fmt.Errorf("leaveapprovals: reading the conferences: %w", err)
		}
		for rows.Next() {
			var a, b, title string
			if err := rows.Scan(&a, &b, &title); err != nil {
				rows.Close()
				return nil, fmt.Errorf("leaveapprovals: reading the conferences: %w", err)
			}
			out = append(out, conflict{kind: "staff_conference", action: "Overlaps with Staff Conference Week: " + title, dates: a + " to " + b})
		}
		rows.Close()
	}
	if l.coverID == "" {
		return out, nil
	}
	rows, err = db.Query(ctx, `SELECT start_date, end_date FROM leave WHERE staff_id = $1 AND status = 'approved' AND start_date <= $2 AND end_date >= $3`,
		l.coverID, l.end, l.start)
	if err != nil {
		return nil, fmt.Errorf("leaveapprovals: reading the cover's leave: %w", err)
	}
	for rows.Next() {
		var a, b string
		if err := rows.Scan(&a, &b); err != nil {
			rows.Close()
			return nil, fmt.Errorf("leaveapprovals: reading the cover's leave: %w", err)
		}
		out = append(out, conflict{kind: "cover_unavailable", action: "Covering person is also on approved leave during this range.", dates: a + " to " + b, critical: true})
	}
	rows.Close()
	if !full {
		return out, nil
	}
	coverOwners, err := ownerIDs(ctx, db, l.coverID)
	if err != nil {
		return nil, err
	}
	var busy int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM activity WHERE deleted_at IS NULL AND responsible_staff_id = ANY($1)
  AND scheduled_date >= $2 AND scheduled_date < $3 AND NOT (status IN ('cancelled', 'completed'))`, coverOwners, from, to).Scan(&busy); err != nil {
		return nil, fmt.Errorf("leaveapprovals: counting the cover's work: %w", err)
	}
	if busy > coverWorkload {
		out = append(out, conflict{kind: "high_workload_cover",
			action: "Covering person has high workload (" + strconv.Itoa(busy) + " activities) during this period.", dates: l.start + " to " + l.end})
	}
	return out, nil
}

// BlackoutDays is get_blackout_dates_in_range for the other leave pages
// (internal/personaltimeoff's impact preview).
func BlackoutDays(ctx context.Context, db schooldirectory.Querier, s, e time.Time) ([]string, error) {
	return blackoutDays(ctx, db, s, e)
}

// blackoutDays is get_blackout_dates_in_range: each blocked day of the
// national calendar inside the leave, in order.
func blackoutDays(ctx context.Context, db schooldirectory.Querier, s, e time.Time) ([]string, error) {
	rows, err := db.Query(ctx, `SELECT start_date, end_date FROM calendar_block
WHERE block_type = 'BLACKOUT_DATE' AND is_active AND country = $1 AND start_date <= $2::date AND end_date >= $3::date`,
		blackoutCountry, e.Format(time.DateOnly), s.Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("leaveapprovals: reading the blackout days: %w", err)
	}
	defer rows.Close()
	days := map[string]bool{}
	for rows.Next() {
		var a, b time.Time
		if err := rows.Scan(&a, &b); err != nil {
			return nil, fmt.Errorf("leaveapprovals: reading the blackout days: %w", err)
		}
		if a.Before(s) {
			a = s
		}
		if b.After(e) {
			b = e
		}
		for d := a; !d.After(b); d = d.AddDate(0, 0, 1) {
			days[d.Format(time.DateOnly)] = true
		}
	}
	out := []string{}
	for d := range days {
		out = append(out, d)
	}
	sort.Strings(out)
	return out, rows.Err()
}

// impact is the part of LeaveImpactAnalysisService.analyze_impact the panel
// reads: the work a leave touches and the balance it draws on.
type impact struct {
	activities, planning, due, partner, funds int
	remaining, entitlement                    *int
}

func analyze(ctx context.Context, db schooldirectory.Querier, l leave) (impact, error) {
	var im impact
	s, _ := parseDay(l.start)
	e, _ := parseDay(l.end)
	from, to := window(s, e)
	owners, err := ownerIDs(ctx, db, l.staffID)
	if err != nil {
		return im, err
	}
	err = db.QueryRow(ctx, `SELECT
  (SELECT count(*) FROM activity WHERE deleted_at IS NULL AND responsible_staff_id = ANY($1) AND scheduled_date >= $2 AND scheduled_date < $3),
  (SELECT count(*) FROM activity WHERE deleted_at IS NULL AND responsible_staff_id = ANY($1) AND scheduled_date >= $2 AND scheduled_date < $3 AND status = ANY($4)),
  (SELECT count(*) FROM monthly_plan_activity WHERE assignee_id = $5 AND scheduled_date BETWEEN $6 AND $7),
  (SELECT count(*) FROM activity WHERE deleted_at IS NULL AND monitored_by_staff_id = $5 AND scheduled_date >= $2 AND scheduled_date < $3
     AND delivery_type = 'partner' AND status = 'planned'),
  (SELECT count(*) FROM fund_request WHERE submitted_by_user_id = $8 AND status = ANY($9))`,
		owners, from, to, liveWork, l.staffID, l.start, l.end, l.staffUser, rules.FundRequestStatuses).
		Scan(&im.activities, &im.due, &im.planning, &im.partner, &im.funds)
	if err != nil {
		return im, fmt.Errorf("leaveapprovals: analysing a leave's impact: %w", err)
	}
	var remaining, entitlement int
	err = db.QueryRow(ctx, `SELECT remaining, entitlement FROM leave_balance WHERE staff_id = $1 AND leave_type = $2 AND year = $3 ORDER BY id LIMIT 1`,
		l.staffID, l.kind, s.Year()).Scan(&remaining, &entitlement)
	switch {
	case err == pgx.ErrNoRows:
	case err != nil:
		return im, fmt.Errorf("leaveapprovals: reading the balance a leave draws on: %w", err)
	default:
		im.remaining, im.entitlement = &remaining, &entitlement
	}
	return im, nil
}

// candidate is one person who may cover a leave.
type candidate struct{ id, name, role string }

// eligibleCover is CoverageAssignmentService.get_eligible_coverage_staff:
// active colleagues not away at the same time, narrowed by the role of the
// person taking leave, in the order the database returns them.
func eligibleCover(ctx context.Context, db schooldirectory.Querier, l leave) ([]candidate, error) {
	base := `sp.deleted_at IS NULL AND sp.onboarding_state = 'active' AND NOT (sp.id = $1)
  AND NOT (sp.id IN (SELECT staff_id FROM leave WHERE status = 'approved' AND start_date <= $2 AND end_date >= $3 AND staff_id IS NOT NULL))`
	args := []any{l.staffID, l.end, l.start}
	var supervisor string
	if err := db.QueryRow(ctx, `SELECT supervisor_id FROM staff_supervisor_assignment WHERE supervisee_id = $1 ORDER BY id LIMIT 1`, l.staffID).Scan(&supervisor); err != nil && err != pgx.ErrNoRows {
		return nil, fmt.Errorf("leaveapprovals: reading the leave's supervisor: %w", err)
	}
	query := func(where string, extra ...any) ([]candidate, error) {
		rows, err := db.Query(ctx, `SELECT sp.id, COALESCE(u.name, ''), COALESCE(u.active_role, 'None') FROM staff_profile sp INNER JOIN "user" u ON (sp.user_id = u.id)
WHERE `+base+` AND `+where, append(append([]any{}, args...), extra...)...)
		if err != nil {
			return nil, fmt.Errorf("leaveapprovals: reading the eligible cover: %w", err)
		}
		return pgx.CollectRows(rows, func(r pgx.CollectableRow) (candidate, error) {
			var c candidate
			return c, r.Scan(&c.id, &c.name, &c.role)
		})
	}
	switch l.staffRole {
	case "CCEO":
		if supervisor == "" {
			return query(`u.active_role = 'CCEO'`)
		}
		return query(`((u.active_role = 'CCEO' AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $4)) OR sp.id = $4)`, supervisor)
	case "Program Lead":
		var leads []candidate
		var err error
		if supervisor == "" {
			leads, err = query(`u.active_role IN ('Program Lead', 'CountryDirector')`)
		} else {
			leads, err = query(`((u.active_role IN ('Program Lead', 'CountryDirector') AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $4)) OR sp.id = $4)`, supervisor)
		}
		if err != nil {
			return nil, err
		}
		seniors, err := query(`u.active_role = 'CCEO' AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $4)`, l.staffID)
		if err != nil {
			return nil, err
		}
		return append(leads, seniors...), nil
	case "CountryDirector":
		return query(`u.active_role IN ('RegionalVicePresident', 'Program Lead')`)
	case "ImpactAssessment":
		return query(`u.active_role IN ('ImpactAssessment', 'CountryDirector')`)
	case "Accountant":
		return query(`u.active_role IN ('Accountant', 'CountryDirector')`)
	}
	all, err := query(`TRUE`)
	if err != nil {
		return nil, err
	}
	return all[:min(10, len(all))], nil
}
