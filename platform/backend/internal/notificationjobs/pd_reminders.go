package notificationjobs

// The pd_reminders job (apps.professional_development.reminders
// .send_due_reminders): the course clock moved on first (sync_dates, which
// closes the reminders a start or an end has answered), then the 7/3/1-day
// reminders before a confirmed course, one a day while it runs, and the
// overdue chase 7, 14 and 30 days after it ended, from 14 days to the
// employee's supervisor and HR too. A log row per request, key and day keeps
// each said once a day.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

const (
	pdCourseStarting    = "pd_course_starting"
	pdCourseInProgress  = "pd_course_in_progress"
	pdCompletionOverdue = "pd_completion_overdue"

	pdConfirmed  = "enrollment_confirmed"
	pdInProgress = "in_progress"
	pdEnded      = "ended"

	countryDirector = "CountryDirector"
)

// reviewerRoleFor is apps.hr.review_authority.REVIEWER_ROLE_FOR.
var reviewerRoleFor = map[string][]string{
	"CCEO": {"Program Lead"}, "Program Lead": {countryDirector}, "ImpactAssessment": {countryDirector},
	"Accountant": {countryDirector}, "ProjectCoordinator": {countryDirector}, "HumanResources": {countryDirector},
	countryDirector: {"RegionalVicePresident"}, "RegionalVicePresident": {"Admin"},
}

// liveStates are review_authority.LIVE_STATES.
var liveStates = []string{"active", "pending"}

// pdRequest is what the reminders read of a request.
type pdRequest struct {
	id, status, course, institution, staffID, staffName, owner string
	start, end                                                 time.Time
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// SendPDReminders says how many reminders reached the employee, as the
// existing job counts them.
func SendPDReminders(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, push activities.NoticePush) (int, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	if err := syncPDDates(ctx, tx, today, now); err != nil {
		return 0, err
	}
	sent := 0
	for _, step := range []func(context.Context, pgx.Tx, time.Time, time.Time, activities.NoticePush) (int, error){
		preCourseReminders, inProgressReminders, overdueReminders,
	} {
		n, err := step(ctx, tx, today, now, push)
		sent += n
		if err != nil {
			return sent, err
		}
	}
	return sent, nil
}

func readPDRequests(ctx context.Context, tx pgx.Tx, statuses ...string) ([]pdRequest, error) {
	rows, err := tx.Query(ctx, `SELECT r.id, r.status, r.course_name, r.institution, r.staff_id, r.staff_name,
  COALESCE((SELECT sp.user_id FROM staff_profile sp WHERE sp.id = r.staff_id LIMIT 1), ''), r.start_date, r.end_date
FROM pd_request r WHERE r.status = ANY($1) ORDER BY r.created_at, r.id`, statuses)
	if err != nil {
		return nil, fmt.Errorf("notificationjobs: reading the PD requests: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (pdRequest, error) {
		var r pdRequest
		err := row.Scan(&r.id, &r.status, &r.course, &r.institution, &r.staffID, &r.staffName, &r.owner, &r.start, &r.end)
		return r, err
	})
}

// syncPDDates is PDCourseTrackingService.sync_dates for every confirmed or
// running course.
func syncPDDates(ctx context.Context, tx pgx.Tx, today, now time.Time) error {
	requests, err := readPDRequests(ctx, tx, pdConfirmed, pdInProgress)
	if err != nil {
		return err
	}
	for _, r := range requests {
		status := r.status
		var answered []string
		if status == pdConfirmed && !today.Before(r.start) {
			status = pdInProgress
			answered = append(answered, pdCourseStarting)
		}
		if status == pdInProgress && !today.Before(r.end) {
			status = pdEnded
			answered = append(answered, pdCourseInProgress)
		}
		if len(answered) == 0 {
			continue
		}
		if _, err := tx.Exec(ctx, `UPDATE pd_request SET status = $2, updated_at = $3 WHERE id = $1`, r.id, status, now); err != nil {
			return fmt.Errorf("notificationjobs: moving the course clock: %w", err)
		}
		for _, event := range answered {
			if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'pd_request', $2, $3)`,
				event, r.id, now); err != nil {
				return fmt.Errorf("notificationjobs: closing the answered PD reminder: %w", err)
			}
		}
	}
	return nil
}

// pdAlreadySent is _already_sent; pdLogSent is _log_sent.
func pdAlreadySent(ctx context.Context, tx pgx.Tx, requestID, key string, today time.Time) (bool, error) {
	var sent bool
	err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM pd_reminder_log WHERE request_id = $1 AND reminder_key = $2
  AND sent_on = $3::date)`, requestID, key, today.Format(time.DateOnly)).Scan(&sent)
	if err != nil {
		return false, fmt.Errorf("notificationjobs: reading the PD reminder log: %w", err)
	}
	return sent, nil
}

func pdLogSent(ctx context.Context, tx pgx.Tx, requestID, key string, today, now time.Time) error {
	if _, err := tx.Exec(ctx, `INSERT INTO pd_reminder_log (id, created_at, updated_at, reminder_key, sent_on, request_id)
VALUES ($1, $2, $2, $3, $4::date, $5) ON CONFLICT DO NOTHING`, cuid.New(), now, key, today.Format(time.DateOnly), requestID); err != nil {
		return fmt.Errorf("notificationjobs: logging the PD reminder: %w", err)
	}
	return nil
}

// pdNotify is reminders._notify: one high-priority notice, linked to the
// request. It says whether one was sent.
func pdNotify(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, recipient, title, body string,
	r pdRequest, event string) (bool, error) {
	if recipient == "" {
		return false, nil
	}
	_, err := activities.NotifyInTx(ctx, tx, push, slog.Default(), now, r.id, activities.Notice{
		Title: title, Body: body, Event: event, Category: "professional_development", ContextType: "pd_request",
		Priority: "high",
	}, []activities.NoticeTo{{UserID: recipient, Route: "/my-professional-development/request?id=" + r.id, Label: "Open Request"}})
	if err != nil {
		return false, fmt.Errorf("notificationjobs: sending the PD reminder: %w", err)
	}
	return true, nil
}

func days(a, b time.Time) int { return int(a.Sub(b).Hours() / 24) }

func preCourseReminders(ctx context.Context, tx pgx.Tx, today, now time.Time, push activities.NoticePush) (int, error) {
	requests, err := readPDRequests(ctx, tx, pdConfirmed)
	if err != nil {
		return 0, err
	}
	sent := 0
	for _, r := range requests {
		left := days(r.start, today)
		if left != 7 && left != 3 && left != 1 {
			continue
		}
		key := fmt.Sprintf("pre_start_%d", left)
		if done, err := pdAlreadySent(ctx, tx, r.id, key, today); err != nil || done {
			if err != nil {
				return sent, err
			}
			continue
		}
		ok, err := pdNotify(ctx, tx, push, now, r.owner, "Your Professional Development course starts soon",
			fmt.Sprintf("“%s” at %s starts in %d day%s (%s).", r.course, r.institution, left, plural(left), r.start.Format("02 Jan 2006")),
			r, pdCourseStarting)
		if err != nil {
			return sent, err
		}
		if ok {
			sent++
		}
		if err := pdLogSent(ctx, tx, r.id, key, today, now); err != nil {
			return sent, err
		}
	}
	return sent, nil
}

func inProgressReminders(ctx context.Context, tx pgx.Tx, today, now time.Time, push activities.NoticePush) (int, error) {
	requests, err := readPDRequests(ctx, tx, pdInProgress)
	if err != nil {
		return 0, err
	}
	sent := 0
	const key = "in_progress_daily"
	for _, r := range requests {
		if done, err := pdAlreadySent(ctx, tx, r.id, key, today); err != nil || done {
			if err != nil {
				return sent, err
			}
			continue
		}
		left := days(r.end, today)
		ok, err := pdNotify(ctx, tx, push, now, r.owner, "Professional Development course in progress",
			fmt.Sprintf("“%s” is in progress — %d day%s remaining.", r.course, left, plural(left)), r, pdCourseInProgress)
		if err != nil {
			return sent, err
		}
		if ok {
			sent++
		}
		if err := pdLogSent(ctx, tx, r.id, key, today, now); err != nil {
			return sent, err
		}
	}
	return sent, nil
}

func overdueReminders(ctx context.Context, tx pgx.Tx, today, now time.Time, push activities.NoticePush) (int, error) {
	requests, err := readPDRequests(ctx, tx, pdEnded)
	if err != nil {
		return 0, err
	}
	sent := 0
	for _, r := range requests {
		over := days(today, r.end)
		if over != 7 && over != 14 && over != 30 {
			continue
		}
		key := fmt.Sprintf("overdue_%d", over)
		if done, err := pdAlreadySent(ctx, tx, r.id, key, today); err != nil || done {
			if err != nil {
				return sent, err
			}
			continue
		}
		body := fmt.Sprintf("“%s” ended %d days ago and has not been marked complete yet.", r.course, over)
		ok, err := pdNotify(ctx, tx, push, now, r.owner, "Mark your Professional Development course complete", body, r, pdCompletionOverdue)
		if err != nil {
			return sent, err
		}
		if ok {
			sent++
		}
		if over >= 14 {
			if err := escalateOverdue(ctx, tx, push, now, r, body); err != nil {
				return sent, err
			}
		}
		if err := pdLogSent(ctx, tx, r.id, key, today, now); err != nil {
			return sent, err
		}
	}
	return sent, nil
}

// escalateOverdue tells the employee's supervisor and every active HR
// holder.
func escalateOverdue(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, r pdRequest, body string) error {
	supervisor, err := pdSupervisor(ctx, tx, r.staffID)
	if err != nil {
		return err
	}
	if supervisor != "" {
		if _, err := pdNotify(ctx, tx, push, now, supervisor, "A team member's PD course is overdue for completion",
			r.staffName+" — "+body, r, pdCompletionOverdue); err != nil {
			return err
		}
	}
	rows, err := tx.Query(ctx, `SELECT id FROM "user" WHERE roles @> ARRAY['HumanResources']::varchar[] AND status = 'active'
  AND deleted_at IS NULL ORDER BY created_at DESC`)
	if err != nil {
		return fmt.Errorf("notificationjobs: reading HR: %w", err)
	}
	hr, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return fmt.Errorf("notificationjobs: reading HR: %w", err)
	}
	for _, id := range hr {
		if _, err := pdNotify(ctx, tx, push, now, id, "A PD course is overdue for completion", r.staffName+" — "+body, r,
			pdCompletionOverdue); err != nil {
			return err
		}
	}
	return nil
}

// pdSupervisor is PDApprovalRoutingService.supervisor_for: the first
// reporting line, by link id, whose live holder works in the role the chart
// names for this person; for a role the Country Director reviews with no
// such line, the Director of the person's country (never the person). It is
// the reviewer's user id, or "".
func pdSupervisor(ctx context.Context, tx pgx.Tx, staffID string) (string, error) {
	_, user, err := PDSupervisorOf(ctx, tx, staffID)
	return user, err
}

// PDSupervisorOf is supervisor_for: the reviewer's People record and user id,
// or "" for both.
func PDSupervisorOf(ctx context.Context, tx pgx.Tx, staffID string) (string, string, error) {
	var activeRole, country string
	err := tx.QueryRow(ctx, `SELECT COALESCE(u.active_role, ''), COALESCE(sp.country, '') FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = $1`, staffID).Scan(&activeRole, &country)
	if err == pgx.ErrNoRows {
		return "", "", nil
	}
	if err != nil {
		return "", "", fmt.Errorf("notificationjobs: reading the employee: %w", err)
	}
	expected := reviewerRoleFor[activeRole]
	if len(expected) == 0 {
		return "", "", nil
	}
	var reviewer, reviewerProfile string
	err = tx.QueryRow(ctx, `SELECT COALESCE(s.user_id, ''), s.id FROM staff_supervisor_assignment l
JOIN staff_profile s ON s.id = l.supervisor_id JOIN "user" u ON u.id = s.user_id
WHERE l.supervisee_id = $1 AND u.active_role = ANY($2) AND u.is_active AND u.deleted_at IS NULL
  AND s.onboarding_state = ANY($3)
ORDER BY l.id LIMIT 1`, staffID, expected, liveStates).Scan(&reviewer, &reviewerProfile)
	if err == nil {
		return reviewerProfile, reviewer, nil
	}
	if err != pgx.ErrNoRows {
		return "", "", fmt.Errorf("notificationjobs: reading the employee's reporting line: %w", err)
	}
	if len(expected) != 1 || expected[0] != countryDirector || country == "" {
		return "", "", nil
	}
	var director, directorProfile string
	err = tx.QueryRow(ctx, `SELECT COALESCE(sp.user_id, ''), sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.country = $1 AND (u.active_role = $2 OR u.roles @> ARRAY[$2::varchar]) AND u.is_active AND u.deleted_at IS NULL
  AND sp.onboarding_state = ANY($3)
ORDER BY u.name, sp.id LIMIT 1`, country, countryDirector, liveStates).Scan(&director, &directorProfile)
	if err == pgx.ErrNoRows || directorProfile == staffID {
		return "", "", nil
	}
	if err != nil {
		return "", "", fmt.Errorf("notificationjobs: reading the country's director: %w", err)
	}
	return directorProfile, director, nil
}
