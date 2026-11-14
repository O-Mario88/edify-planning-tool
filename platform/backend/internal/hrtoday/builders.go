package hrtoday

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The four queues.
const (
	waitingOnHR    = "waiting_on_hr"
	managerOverdue = "manager_overdue"
	peopleRisk     = "people_risk"
	deadlines      = "deadlines"
)

// The builders' own caps and windows.
const (
	queueCap     = 50
	documentCap  = 25
	rosterCap    = 500
	departedCap  = 10
	lateReview   = 14
	coverHorizon = 14
)

const conversationURL = "/performance-conversation?staff="

var severityOrder = map[string]int{"critical": 0, "high": 1, "medium": 2}

// exception is one HRException.
type exception struct {
	group, kind, title, detail, url, severity, person, due string
	sortA, sortB                                           int
}

func personName(name, email string) string {
	switch {
	case name != "":
		return name
	case email != "":
		return email
	}
	return "Staff member"
}

func daysAgo(days int) string {
	switch {
	case days <= 0:
		return "today"
	case days == 1:
		return "1 day"
	}
	return strconv.Itoa(days) + " days"
}

func days(a, b time.Time) int { return int(a.Sub(b).Hours() / 24) }

func dueLabel(target, today time.Time) string {
	delta := days(target, today)
	switch {
	case delta < 0:
		return strconv.Itoa(-delta) + " days overdue"
	case delta == 0:
		return "due today"
	case delta == 1:
		return "due tomorrow"
	}
	return "in " + strconv.Itoa(delta) + " days"
}

// pyTitle is str.title().
func pyTitle(s string) string {
	var b strings.Builder
	prev := false
	for _, r := range s {
		letter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case letter && !prev:
			b.WriteString(strings.ToUpper(string(r)))
		case letter:
			b.WriteString(strings.ToLower(string(r)))
		default:
			b.WriteRune(r)
		}
		prev = letter
	}
	return b.String()
}

// utcDay is created_at.date() on the UTC instant the database hands back.
func utcDay(t time.Time) time.Time {
	u := t.UTC()
	return time.Date(u.Year(), u.Month(), u.Day(), 0, 0, 0, 0, time.UTC)
}

// builder reads the exceptions of one reader's scope.
type builder struct {
	db     schooldirectory.Querier
	ids    []string
	scoped string
	args   []any
	today  time.Time
	fy     string
}

func (b builder) escalatedLeave(ctx context.Context) ([]exception, error) {
	rows, err := b.db.Query(ctx, `SELECT l.id, l.type, l.start_date, l.end_date, l.created_at, COALESCE(u.name, ''), COALESCE(u.email, '')
FROM leave l JOIN staff_profile sp ON sp.id = l.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE l.status = 'hr_review' AND l.staff_id = ANY($1) ORDER BY l.created_at LIMIT $2`, b.ids, queueCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading escalated leave: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var id, kind, start, end, name, email string
		var created time.Time
		if err := rows.Scan(&id, &kind, &start, &end, &created, &name, &email); err != nil {
			return nil, fmt.Errorf("hrtoday: reading escalated leave: %w", err)
		}
		waited := days(b.today, utcDay(created))
		sev := "medium"
		if waited >= rules.LeaveDecisionDays {
			sev = "high"
		}
		out = append(out, exception{group: waitingOnHR, kind: "leave_escalated", title: "Leave escalated to HR",
			detail: pyTitle(strings.ReplaceAll(kind, "_", " ")) + ", " + start + " to " + end + ". Waiting " + daysAgo(waited) + ".",
			url:    "/leave/approvals?id=" + id, severity: sev, person: personName(name, email), due: "waiting " + daysAgo(waited), sortB: -waited})
	}
	return out, rows.Err()
}

func (b builder) pdAwaitingHR(ctx context.Context) ([]exception, error) {
	labels := map[string]string{
		"submitted_to_hr":     "Professional Development request needs HR review",
		"pending_exception":   "Professional Development exception needs HR",
		"awaiting_hr_signoff": "Professional Development completion needs HR sign-off",
	}
	rows, err := b.db.Query(ctx, `SELECT id, status, COALESCE(course_name, ''), COALESCE(staff_name, '') FROM pd_request
WHERE staff_id = ANY($1) AND status IN ('submitted_to_hr', 'pending_exception', 'awaiting_hr_signoff') ORDER BY submitted_at LIMIT $2`, b.ids, queueCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading development requests: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var id, status, course, staff string
		if err := rows.Scan(&id, &status, &course, &staff); err != nil {
			return nil, fmt.Errorf("hrtoday: reading development requests: %w", err)
		}
		if course == "" {
			course = "Course"
		}
		sev := "medium"
		if status == "pending_exception" {
			sev = "high"
		}
		out = append(out, exception{group: waitingOnHR, kind: "pd_" + status, title: labels[status],
			detail: strings.Trim(course+" — "+staff, " —"), url: "/my-professional-development/request?id=" + id, severity: sev, person: staff})
	}
	return out, rows.Err()
}

func policiesAwaiting(ctx context.Context, db schooldirectory.Querier) ([]exception, error) {
	labels := map[string]string{"approved": "Approved and waiting to be published", "under_review": "Waiting for a reviewer's decision",
		"returned": "Returned for revision"}
	rows, err := db.Query(ctx, `SELECT status, COALESCE(title, ''), COALESCE(slug, '') FROM document_asset
WHERE status = ANY($1) AND archived_at IS NULL ORDER BY updated_at LIMIT $2`, rules.PolicyAwaitingStatuses, documentCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading policies: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var status, title, slug string
		if err := rows.Scan(&status, &title, &slug); err != nil {
			return nil, fmt.Errorf("hrtoday: reading policies: %w", err)
		}
		out = append(out, exception{group: waitingOnHR, kind: "policy_" + status, title: labels[status], detail: title,
			url: "/documents/" + slug + "/manage", severity: "medium"})
	}
	return out, rows.Err()
}

// probation is _probation_decisions_due (due) and _probation_ending.
func (b builder) probation(ctx context.Context, due bool) ([]exception, error) {
	cond := "p.probation_review_date IS NOT NULL AND p.probation_review_date <= $2::date"
	args := []any{b.ids, b.today.Format(time.DateOnly), queueCap}
	if !due {
		cond = "p.probation_review_date > $2::date AND p.probation_review_date <= $4::date"
		args = append(args, b.today.AddDate(0, 0, rules.DeadlineHorizonDays).Format(time.DateOnly))
	}
	rows, err := b.db.Query(ctx, `SELECT p.probation_review_date, COALESCE(u.name, ''), COALESCE(u.email, '')
FROM hr_onboarding_plan p JOIN staff_profile sp ON sp.id = p.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE p.staff_id = ANY($1) AND `+cond+` AND p.status IS DISTINCT FROM 'closed' ORDER BY p.probation_review_date LIMIT $3`, args...)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading probation reviews: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var on time.Time
		var name, email string
		if err := rows.Scan(&on, &name, &email); err != nil {
			return nil, fmt.Errorf("hrtoday: reading probation reviews: %w", err)
		}
		d := on.Format(time.DateOnly)
		if due {
			out = append(out, exception{group: waitingOnHR, kind: "probation_decision_due", title: "Probation decision due",
				detail: "Probation review date was " + d + ". Confirm, extend or end.", url: "/onboarding", severity: "high",
				person: personName(name, email), due: dueLabel(on, b.today)})
			continue
		}
		out = append(out, exception{group: deadlines, kind: "probation_ending", title: "Probation period ending",
			detail: "Review due " + d + " — a decision is needed before it lapses.", url: "/onboarding", severity: "medium",
			person: personName(name, email), due: dueLabel(on, b.today), sortA: 3, sortB: days(on, b.today)})
	}
	return out, rows.Err()
}

func (b builder) leaveOverdue(ctx context.Context) ([]exception, error) {
	cutoff := b.today.AddDate(0, 0, -rules.LeaveDecisionDays)
	rows, err := b.db.Query(ctx, `SELECT l.id, l.created_at, COALESCE(u.name, ''), COALESCE(u.email, '')
FROM leave l JOIN staff_profile sp ON sp.id = l.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE l.status = 'pending' AND l.staff_id = ANY($1) AND (l.created_at AT TIME ZONE 'Africa/Kampala')::date <= $2::date
ORDER BY l.created_at LIMIT $3`, b.ids, cutoff.Format(time.DateOnly), queueCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading undecided leave: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var id, name, email string
		var created time.Time
		if err := rows.Scan(&id, &created, &name, &email); err != nil {
			return nil, fmt.Errorf("hrtoday: reading undecided leave: %w", err)
		}
		waited := days(b.today, utcDay(created))
		sev := "medium"
		if waited >= rules.LeaveDecisionDays*2 {
			sev = "high"
		}
		out = append(out, exception{group: managerOverdue, kind: "leave_decision_overdue", title: "Leave request has no decision",
			detail: "Submitted " + daysAgo(waited) + " ago and still pending with the manager.", url: "/leave/approvals?id=" + id,
			severity: sev, person: personName(name, email), due: "waiting " + daysAgo(waited), sortA: 1, sortB: -waited})
	}
	return out, rows.Err()
}

func (b builder) reviewsOverdue(ctx context.Context) ([]exception, error) {
	rows, err := b.db.Query(ctx, `SELECT r.staff_id, r.due_date, COALESCE(NULLIF(r.period, ''), NULLIF(r.fy, ''), ''), COALESCE(u.name, ''), COALESCE(u.email, '')
FROM hr_performance_review r JOIN staff_profile sp ON sp.id = r.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE r.staff_id = ANY($1) AND r.due_date IS NOT NULL AND r.due_date < $2::date
  AND NOT COALESCE(r.stage IN ('closed', 'signed_and_archived'), FALSE) AND NOT COALESCE(r.status IN ('Completed', 'Closed'), FALSE)
ORDER BY r.due_date LIMIT $3`, b.ids, b.today.AddDate(0, 0, -rules.ReviewOverdueDays).Format(time.DateOnly), queueCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading overdue reviews: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var staff, period, name, email string
		var due time.Time
		if err := rows.Scan(&staff, &due, &period, &name, &email); err != nil {
			return nil, fmt.Errorf("hrtoday: reading overdue reviews: %w", err)
		}
		late := days(b.today, due)
		sev := "medium"
		if late > lateReview {
			sev = "high"
		}
		out = append(out, exception{group: managerOverdue, kind: "review_overdue", title: "Performance review overdue",
			detail: strings.TrimSpace(period + " review is " + strconv.Itoa(late) + " days late."), url: conversationURL + staff,
			severity: sev, person: personName(name, email), due: dueLabel(due, b.today), sortA: 1, sortB: -late})
	}
	return out, rows.Err()
}

// roster is the scoped People records narrowed by cond, in database order,
// at most limit of them.
func (b builder) roster(ctx context.Context, cond string, limit int, extra ...any) ([][3]string, error) {
	rows, err := b.db.Query(ctx, `SELECT sp.id, COALESCE(u.name, ''), COALESCE(u.email, ''), COALESCE(u.active_role, ''), COALESCE(sp.user_id, ''), COALESCE(sp.onboarding_state, '')
FROM staff_profile sp INNER JOIN "user" u ON (sp.user_id = u.id) WHERE `+b.scoped+` AND `+cond+` LIMIT `+strconv.Itoa(limit), append(append([]any{}, b.args...), extra...)...)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading the roster: %w", err)
	}
	defer rows.Close()
	out := [][3]string{}
	for rows.Next() {
		var id, name, email, role, user, state string
		if err := rows.Scan(&id, &name, &email, &role, &user, &state); err != nil {
			return nil, fmt.Errorf("hrtoday: reading the roster: %w", err)
		}
		// [id, name, role|user|state]
		out = append(out, [3]string{id, personName(name, email), role + "\x00" + user + "\x00" + state})
	}
	return out, rows.Err()
}

func field(x [3]string, i int) string { return strings.Split(x[2], "\x00")[i] }

func (b builder) withoutSupervisor(ctx context.Context) ([]exception, error) {
	active, err := b.roster(ctx, "sp.onboarding_state = 'active'", rosterCap)
	if err != nil || len(active) == 0 {
		return nil, err
	}
	ids := []string{}
	for _, x := range active {
		ids = append(ids, x[0])
	}
	rows, err := b.db.Query(ctx, `SELECT a.supervisee_id, COALESCE(u.active_role, '') FROM staff_supervisor_assignment a
JOIN staff_profile s ON s.id = a.supervisor_id JOIN "user" u ON u.id = s.user_id
WHERE a.supervisee_id = ANY($1) AND u.is_active AND u.deleted_at IS NULL AND s.onboarding_state = ANY($2)`, ids, rules.LiveStates)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading the reporting lines: %w", err)
	}
	anyLink, links := map[string]bool{}, map[string][]string{}
	for rows.Next() {
		var who, role string
		if err := rows.Scan(&who, &role); err != nil {
			rows.Close()
			return nil, fmt.Errorf("hrtoday: reading the reporting lines: %w", err)
		}
		anyLink[who] = true
		links[who] = append(links[who], role)
	}
	rows.Close()
	out := []exception{}
	for _, x := range active {
		expected := rules.ReviewerRoleFor[field(x, 0)]
		if len(expected) == 0 {
			continue
		}
		matches := 0
		for _, r := range links[x[0]] {
			if slices.Contains(expected, r) {
				matches++
			}
		}
		e := exception{group: peopleRisk, kind: "no_supervisor", url: "/org-structure", severity: "high", person: x[1], sortA: 2}
		switch {
		case matches == 1:
			continue
		case matches > 1:
			e.kind, e.title = "two_managers", "Employee has two managers"
			e.detail = "Two people hold the reporting line, so it is undefined who conducts their review."
		case anyLink[x[0]]:
			e.title = "Employee's manager cannot review them"
			e.detail = "Their reporting link is an oversight row, not the reporting line, so nobody can conduct their review."
		default:
			e.title = "Active employee has no manager"
			e.detail = "Nobody can approve their leave, review their performance or receive their escalations."
		}
		out = append(out, e)
	}
	return out[:min(queueCap, len(out))], nil
}

func usersWithoutRecord(ctx context.Context, db schooldirectory.Querier) ([]exception, error) {
	rows, err := db.Query(ctx, `SELECT COALESCE(u.name, ''), COALESCE(u.email, '') FROM "user" u LEFT OUTER JOIN staff_profile sp ON (u.id = sp.user_id)
WHERE u.is_active AND u.deleted_at IS NULL AND sp.id IS NULL ORDER BY u.name LIMIT $1`, queueCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading accounts without a People record: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var name, email string
		if err := rows.Scan(&name, &email); err != nil {
			return nil, fmt.Errorf("hrtoday: reading accounts without a People record: %w", err)
		}
		if name == "" {
			name = email
		}
		out = append(out, exception{group: peopleRisk, kind: "no_people_record", title: "Account has no People record",
			detail: "They can sign in, but hold no country, department, manager or performance agreement — and appear in no HR report.",
			url:    "/admin-panel/users", severity: "high", person: name, sortA: 2})
	}
	return out, rows.Err()
}

func (b builder) leaveWithoutCover(ctx context.Context) ([]exception, error) {
	rows, err := b.db.Query(ctx, `SELECT l.start_date, l.end_date, COALESCE(u.name, ''), COALESCE(u.email, ''),
  l.id IN (SELECT leave_request_id FROM temporary_coverage_assignment WHERE status = 'active' AND leave_request_id IS NOT NULL)
FROM leave l JOIN staff_profile sp ON sp.id = l.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE l.status = 'approved' AND l.staff_id = ANY($1) AND l.end_date >= $2 AND l.start_date <= $3 AND l.covering_staff_id IS NULL
ORDER BY l.start_date LIMIT $4`, b.ids, b.today.Format(time.DateOnly), b.today.AddDate(0, 0, coverHorizon).Format(time.DateOnly), queueCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading uncovered leave: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var start, end, name, email string
		var covered bool
		if err := rows.Scan(&start, &end, &name, &email, &covered); err != nil {
			return nil, fmt.Errorf("hrtoday: reading uncovered leave: %w", err)
		}
		if covered {
			continue
		}
		out = append(out, exception{group: peopleRisk, kind: "leave_without_coverage", title: "Approved leave with nobody covering",
			detail: start + " to " + end + ". Their approvals and To-Dos stay with them while they are away.", url: "/leave/coverage",
			severity: "high", person: personName(name, email), due: "starts " + start, sortA: 2})
	}
	return out, rows.Err()
}

func (b builder) agreements(ctx context.Context) ([]exception, error) {
	active, err := b.roster(ctx, "sp.onboarding_state = 'active'", 1<<30)
	if err != nil || len(active) == 0 {
		return nil, err
	}
	ids, names := []string{}, map[string]string{}
	for _, x := range active {
		ids = append(ids, x[0])
		names[x[0]] = x[1]
	}
	rows, err := b.db.Query(ctx, `SELECT DISTINCT staff_id FROM hr_performance_review WHERE staff_id = ANY($1) AND fy = $2 AND review_type = 'annual_priorities' AND staff_id IS NOT NULL`, ids, b.fy)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading the agreements: %w", err)
	}
	with, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading the agreements: %w", err)
	}
	n := len(b.args) + 1
	missing, err := b.roster(ctx, "sp.onboarding_state = 'active' AND NOT (sp.id = ANY($"+strconv.Itoa(n)+"))", queueCap, with)
	if err != nil {
		return nil, err
	}
	out := []exception{}
	for _, x := range missing {
		out = append(out, exception{group: peopleRisk, kind: "no_agreement", title: "Active employee has no performance agreement",
			detail: "No FY" + b.fy + " agreement, so none of their delivery counts towards anything.", url: "/hr/performance-cycle",
			severity: "high", person: x[1], sortA: 2})
	}
	rows, err = b.db.Query(ctx, `SELECT r.staff_id, sum(p.weight), count(p.id) FROM hr_performance_priority p JOIN hr_performance_review r ON r.id = p.review_id
WHERE r.staff_id = ANY($1) AND r.fy = $2 AND r.review_type = 'annual_priorities' GROUP BY r.id, r.staff_id`, ids, b.fy)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading agreement weights: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var staff string
		var total *int64
		var count int
		if err := rows.Scan(&staff, &total, &count); err != nil {
			return nil, fmt.Errorf("hrtoday: reading agreement weights: %w", err)
		}
		if count == 0 || (total != nil && *total == 100) {
			continue
		}
		shown := "None"
		if total != nil {
			shown = strconv.FormatInt(*total, 10)
		}
		out = append(out, exception{group: peopleRisk, kind: "weights_not_100", title: "Priority weights do not total 100",
			detail: "They total " + shown + ", so every weighted score on this agreement is wrong.", url: conversationURL + staff,
			severity: "high", person: names[staff], sortA: 2})
	}
	return out, rows.Err()
}

func (b builder) departed(ctx context.Context) ([]exception, error) {
	gone, err := b.roster(ctx, "sp.onboarding_state IN ('suspended', 'exited')", 1<<30)
	if err != nil {
		return nil, err
	}
	out := []exception{}
	if len(gone) > departedCap {
		out = append(out, exception{group: peopleRisk, kind: "departed_review_truncated", title: strconv.Itoa(len(gone)) + " departed employees to review",
			detail: "Showing the first 10. Open Offboarding for the full list.", url: "/offboarding", severity: "high", sortA: 2})
	}
	for _, x := range gone[:min(departedCap, len(gone))] {
		ids := []string{x[0]}
		if u := field(x, 1); u != "" {
			ids = []string{u, x[0]}
		}
		var schools, open, reports int
		if err := b.db.QueryRow(ctx, `SELECT
  (SELECT count(*) FROM school WHERE account_owner_id = ANY($1) AND deleted_at IS NULL),
  (SELECT count(*) FROM activity WHERE responsible_staff_id = ANY($1) AND deleted_at IS NULL AND NOT (status IN ('closed', 'cancelled', 'completed'))),
  (SELECT count(*) FROM staff_supervisor_assignment a JOIN staff_profile s ON s.id = a.supervisee_id WHERE a.supervisor_id = $2 AND s.deleted_at IS NULL)`,
			ids, x[0]).Scan(&schools, &open, &reports); err != nil {
			return nil, fmt.Errorf("hrtoday: reading a departed person's work: %w", err)
		}
		held := []string{}
		for _, h := range []struct {
			label string
			n     int
		}{{"direct_reports", reports}, {"open_activities", open}, {"schools", schools}} {
			if h.n > 0 {
				held = append(held, strconv.Itoa(h.n)+" "+h.label)
			}
		}
		if len(held) == 0 {
			continue
		}
		out = append(out, exception{group: peopleRisk, kind: "departed_holding_work", title: pyTitle(field(x, 2)) + " employee still holds work",
			detail: "Still assigned: " + strings.Join(held, ", ") + ".", url: "/offboarding", severity: "critical", person: x[1], sortA: 2})
	}
	return out, nil
}

func (b builder) compliance(ctx context.Context) ([]exception, error) {
	rows, err := b.db.Query(ctx, `SELECT c.expiry_date, COALESCE(q.name, ''), COALESCE(u.name, ''), COALESCE(u.email, '')
FROM hr_employee_compliance_record c JOIN hr_compliance_requirement q ON q.id = c.requirement_id
JOIN staff_profile sp ON sp.id = c.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE c.staff_id = ANY($1) AND c.expiry_date IS NOT NULL AND c.expiry_date <= $2::date ORDER BY c.expiry_date LIMIT $3`,
		b.ids, b.today.AddDate(0, 0, rules.DeadlineHorizonDays).Format(time.DateOnly), queueCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading compliance documents: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var on time.Time
		var requirement, name, email string
		if err := rows.Scan(&on, &requirement, &name, &email); err != nil {
			return nil, fmt.Errorf("hrtoday: reading compliance documents: %w", err)
		}
		title, sev := "Compliance document expiring", "medium"
		if on.Before(b.today) {
			title, sev = "Compliance document expired", "high"
		}
		out = append(out, exception{group: deadlines, kind: "compliance_expiry", title: title,
			detail: requirement + " — " + on.Format(time.DateOnly) + ".", url: "/compliance-register", severity: sev,
			person: personName(name, email), due: dueLabel(on, b.today), sortA: 3, sortB: days(on, b.today)})
	}
	return out, rows.Err()
}

func policyReviews(ctx context.Context, db schooldirectory.Querier, today time.Time) ([]exception, error) {
	rows, err := db.Query(ctx, `SELECT v.review_date, v.version_number, COALESCE(d.title, ''), COALESCE(d.slug, '')
FROM document_version v JOIN document_asset d ON d.id = v.document_id
WHERE v.review_date IS NOT NULL AND v.review_date <= $1::date AND d.status IN ('published', 'effective') AND v.superseded_at IS NULL
ORDER BY v.review_date LIMIT $2`, today.AddDate(0, 0, rules.DeadlineHorizonDays).Format(time.DateOnly), documentCap)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading policy reviews: %w", err)
	}
	defer rows.Close()
	out := []exception{}
	for rows.Next() {
		var on time.Time
		var version int
		var title, slug string
		if err := rows.Scan(&on, &version, &title, &slug); err != nil {
			return nil, fmt.Errorf("hrtoday: reading policy reviews: %w", err)
		}
		label, sev := "Policy review date approaching", "medium"
		if on.Before(today) {
			label, sev = "Policy review date passed", "high"
		}
		out = append(out, exception{group: deadlines, kind: "policy_review_due", title: label,
			detail: title + " (v" + strconv.Itoa(version) + ") — " + on.Format(time.DateOnly) + ".", url: "/documents/" + slug + "/manage",
			severity: sev, due: dueLabel(on, today), sortA: 3, sortB: days(on, today)})
	}
	return out, rows.Err()
}

// unlinkConversations is _unlink_closed_conversations: a conversation the
// reader is not part of keeps its exception and loses its link.
func unlinkConversations(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time, items []exception) error {
	if slices.Contains(rules.GoverningRoles, p.ActiveRole) {
		return nil
	}
	ids := []string{}
	for _, x := range items {
		if strings.HasPrefix(x.url, conversationURL) {
			ids = append(ids, strings.TrimPrefix(x.url, conversationURL))
		}
	}
	if len(ids) == 0 {
		return nil
	}
	var own string
	if err := db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1`, p.UserID).Scan(&own); err != nil && err != pgx.ErrNoRows {
		return fmt.Errorf("hrtoday: reading the reader's People record: %w", err)
	}
	openable := map[string]bool{}
	if own != "" {
		openable[own] = true
	}
	rows, err := db.Query(ctx, `SELECT staff_id FROM hr_performance_review WHERE staff_id = ANY($1) AND fy = $2 AND review_type = 'annual_priorities' AND functional_manager_id = $3`,
		ids, fy, p.UserID)
	if err != nil {
		return fmt.Errorf("hrtoday: reading functional managers: %w", err)
	}
	functional, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return fmt.Errorf("hrtoday: reading functional managers: %w", err)
	}
	for _, id := range functional {
		openable[id] = true
	}
	if own != "" {
		reviewable, err := reviewableBy(ctx, db, ids, own, now)
		if err != nil {
			return err
		}
		for id := range reviewable {
			openable[id] = true
		}
	}
	for i, x := range items {
		if strings.HasPrefix(x.url, conversationURL) && !openable[strings.TrimPrefix(x.url, conversationURL)] {
			items[i].url = ""
		}
	}
	return nil
}

// reviewableBy is review_authority.reviewable_by for the reader's People
// record: the people whose live reviewer it is, or covers now.
func reviewableBy(ctx context.Context, db schooldirectory.Querier, ids []string, own string, now time.Time) (map[string]bool, error) {
	rows, err := db.Query(ctx, `SELECT sp.id, COALESCE(u.active_role, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading the people under review: %w", err)
	}
	expected := map[string][]string{}
	for rows.Next() {
		var id, role string
		if err := rows.Scan(&id, &role); err != nil {
			rows.Close()
			return nil, fmt.Errorf("hrtoday: reading the people under review: %w", err)
		}
		if e := rules.ReviewerRoleFor[role]; len(e) > 0 && id != own {
			expected[id] = e
		}
	}
	rows.Close()
	out := map[string]bool{}
	if len(expected) == 0 {
		return out, nil
	}
	staff := []string{}
	for id := range expected {
		staff = append(staff, id)
	}
	sort.Strings(staff)
	rows, err = db.Query(ctx, `SELECT a.supervisee_id, a.supervisor_id, COALESCE(u.active_role, ''),
  (u.is_active AND u.deleted_at IS NULL AND s.onboarding_state = ANY($2)),
  EXISTS (SELECT 1 FROM temporary_coverage_assignment t WHERE t.original_staff_id = a.supervisor_id AND t.covering_staff_id = $3
    AND t.status = 'active' AND t.start_datetime <= $4 AND t.end_datetime >= $4)
FROM staff_supervisor_assignment a JOIN staff_profile s ON s.id = a.supervisor_id JOIN "user" u ON u.id = s.user_id
WHERE a.supervisee_id = ANY($1)`, staff, rules.LiveStates, own, now)
	if err != nil {
		return nil, fmt.Errorf("hrtoday: reading the reviewers: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var who, reviewer, role string
		var live, covered bool
		if err := rows.Scan(&who, &reviewer, &role, &live, &covered); err != nil {
			return nil, fmt.Errorf("hrtoday: reading the reviewers: %w", err)
		}
		if live && slices.Contains(expected[who], role) && (reviewer == own || covered) {
			out[who] = true
		}
	}
	return out, rows.Err()
}
