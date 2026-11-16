package myteam

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/escalations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// member is one officer the lead line-manages (team_members).
type member struct {
	staffID, userID, name, title, email, onboarding, homeDistrict string
}

// teamMembers is _read_team_members: the live CCEOs (by the role they hold)
// supervised by the lead, or by a Programme Lead the lead covers right now,
// never the lead themself, by name.
func teamMembers(ctx context.Context, db schooldirectory.Querier, profileID string, now time.Time) ([]member, error) {
	rows, err := db.Query(ctx, `
WITH sup AS (
  SELECT $1::text AS id
  UNION
  SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND (u.active_role = $3 OR $3 = ANY(u.roles))
    AND sp.id IN (SELECT original_staff_id FROM temporary_coverage_assignment
                  WHERE covering_staff_id = $1 AND start_datetime <= $2 AND end_datetime >= $2 AND status = 'active'))
SELECT sp.id, sp.user_id, COALESCE(u.name, ''), COALESCE(sp.title, ''), COALESCE(u.email, ''),
       COALESCE(sp.onboarding_state, ''), COALESCE(d.name, '')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id LEFT JOIN district d ON d.id = sp.primary_district_id
WHERE sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id IN (SELECT id FROM sup))
  AND (u.active_role = $4 OR $4 = ANY(u.roles))
  AND sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.is_active AND sp.id <> $1
ORDER BY u.name`, profileID, now, rolePL, roleCCEO)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the team: %w", err)
	}
	defer rows.Close()
	out := []member{}
	for rows.Next() {
		var m member
		if err := rows.Scan(&m.staffID, &m.userID, &m.name, &m.title, &m.email, &m.onboarding, &m.homeDistrict); err != nil {
			return nil, fmt.Errorf("myteam: reading an officer: %w", err)
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

// portfolio is _portfolio: each officer's operating schools and the district
// most of them sit in, else their People record's district.
type portfolio struct {
	byStaff    map[string]map[string]bool
	all        []string
	districtOf map[string]string
}

func readPortfolio(ctx context.Context, db schooldirectory.Querier, members []member) (portfolio, error) {
	staff := ids(members, func(m member) string { return m.staffID })
	p := portfolio{byStaff: map[string]map[string]bool{}, districtOf: map[string]string{}}
	rows, err := db.Query(ctx, `
SELECT a.staff_id, a.school_id, COALESCE(d.name, '')
FROM staff_school_assignment a JOIN school s ON s.id = a.school_id LEFT JOIN district d ON d.id = s.district_id
WHERE a.staff_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)`, staff, rules.OperatingStatuses)
	if err != nil {
		return p, fmt.Errorf("myteam: reading the portfolios: %w", err)
	}
	defer rows.Close()
	seen := map[string]bool{}
	counts := map[string]map[string]int{}
	schoolDistrict := map[string]string{}
	for rows.Next() {
		var staffID, school, district string
		if err := rows.Scan(&staffID, &school, &district); err != nil {
			return p, fmt.Errorf("myteam: reading a portfolio school: %w", err)
		}
		if p.byStaff[staffID] == nil {
			p.byStaff[staffID] = map[string]bool{}
		}
		if p.byStaff[staffID][school] {
			continue
		}
		p.byStaff[staffID][school] = true
		schoolDistrict[school] = district
		if !seen[school] {
			seen[school] = true
			p.all = append(p.all, school)
		}
		if district != "" {
			if counts[staffID] == nil {
				counts[staffID] = map[string]int{}
			}
			counts[staffID][district]++
		}
	}
	if err := rows.Err(); err != nil {
		return p, fmt.Errorf("myteam: reading the portfolios: %w", err)
	}
	for _, m := range members {
		best, most := "", 0
		names := make([]string, 0, len(counts[m.staffID]))
		for name := range counts[m.staffID] {
			names = append(names, name)
		}
		// Counter.most_common(1): the largest count. Python breaks a tie by
		// the order the schools came, which is a set's: Go takes the first
		// name in order, so a tie is the one case the two may differ.
		sort.Strings(names)
		for _, name := range names {
			if n := counts[m.staffID][name]; n > most {
				best, most = name, n
			}
		}
		if best == "" {
			best = m.homeDistrict
		}
		p.districtOf[m.staffID] = best
	}
	return p, nil
}

func ids(members []member, of func(member) string) []string {
	out := []string{}
	for _, m := range members {
		if v := of(m); v != "" {
			out = append(out, v)
		}
	}
	return out
}

// delivery is _delivery: (planned, verified) per officer and the completions
// waiting on the lead.
func readDelivery(ctx context.Context, db schooldirectory.Querier, members []member, p portfolio, fy string) (map[string][2]int, map[string]int, error) {
	ownerOf := map[string]string{}
	keys := []string{}
	for _, m := range members {
		ownerOf[m.staffID] = m.staffID
		keys = append(keys, m.staffID)
		if m.userID != "" {
			ownerOf[m.userID] = m.staffID
			keys = append(keys, m.userID)
		}
	}
	schoolOwner := map[string][]string{}
	for staffID, schools := range p.byStaff {
		for school := range schools {
			schoolOwner[school] = append(schoolOwner[school], staffID)
		}
	}
	rows, err := db.Query(ctx, `
SELECT COALESCE(responsible_staff_id, ''), COALESCE(monitored_by_staff_id, ''), COALESCE(school_id, ''), status, count(*)
FROM activity
WHERE fy = $1 AND deleted_at IS NULL AND status <> ALL($2)
  AND (responsible_staff_id = ANY($3)
       OR (responsible_staff_id IS NULL AND monitored_by_staff_id = ANY($3))
       OR school_id IN (SELECT school_id FROM staff_school_assignment WHERE staff_id = ANY($4)))
GROUP BY 1, 2, 3, 4`, fy, rules.NotInPlanStatuses, keys, ids(members, func(m member) string { return m.staffID }))
	if err != nil {
		return nil, nil, fmt.Errorf("myteam: reading the delivery: %w", err)
	}
	defer rows.Close()
	delivery := map[string][2]int{}
	completions := map[string]int{}
	for rows.Next() {
		var responsible, monitored, school, status string
		var n int
		if err := rows.Scan(&responsible, &monitored, &school, &status, &n); err != nil {
			return nil, nil, fmt.Errorf("myteam: reading the delivery: %w", err)
		}
		owners := map[string]bool{}
		for _, s := range schoolOwner[school] {
			owners[s] = true
		}
		mapped := ownerOf[responsible]
		if responsible != "" && mapped != "" {
			owners[mapped] = true
		}
		for staffID := range owners {
			c := delivery[staffID]
			c[0] += n
			if slices.Contains(rules.VerifiedStatuses, status) {
				c[1] += n
			}
			delivery[staffID] = c
		}
		if status == rules.AwaitingPLStatus {
			submitter := mapped
			if responsible == "" {
				submitter = ownerOf[monitored]
			}
			if submitter != "" {
				completions[submitter] += n
			}
		}
	}
	return delivery, completions, rows.Err()
}

// readSSA is _ssa_coverage: portfolio schools with a confirmed
// self-assessment this year.
func readSSA(ctx context.Context, db schooldirectory.Querier, p portfolio, fy string) (map[string]bool, error) {
	out := map[string]bool{}
	if len(p.all) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT DISTINCT school_id FROM ssa_record
WHERE school_id = ANY($1) AND fy = $2 AND verification_status = 'confirmed' AND deleted_at IS NULL`, p.all, fy)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the SSA coverage: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var school string
		if err := rows.Scan(&school); err != nil {
			return nil, fmt.Errorf("myteam: reading the SSA coverage: %w", err)
		}
		out[school] = true
	}
	return out, rows.Err()
}

// leave is _leave: away now (until when), next away, requests waiting, and
// the approved spans the pace calendar reads.
type leave struct {
	awayNow, nextAway map[string]time.Time
	pending           map[string]int
	approved          map[string][][2]time.Time
}

func readLeave(ctx context.Context, db schooldirectory.Querier, members []member, today time.Time) (leave, error) {
	l := leave{awayNow: map[string]time.Time{}, nextAway: map[string]time.Time{}, pending: map[string]int{},
		approved: map[string][][2]time.Time{}}
	for _, m := range members {
		l.approved[m.staffID] = nil
	}
	rows, err := db.Query(ctx, `
SELECT staff_id, status, COALESCE(start_date, ''), COALESCE(end_date, '')
FROM leave WHERE staff_id = ANY($1) AND status IN ('approved', 'pending')`, ids(members, func(m member) string { return m.staffID }))
	if err != nil {
		return l, fmt.Errorf("myteam: reading the leave: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var staffID, status, start, end string
		if err := rows.Scan(&staffID, &status, &start, &end); err != nil {
			return l, fmt.Errorf("myteam: reading a leave: %w", err)
		}
		if status == "pending" {
			l.pending[staffID]++
			continue
		}
		s, e, ok := targets.Span(start, end)
		if !ok {
			continue
		}
		l.approved[staffID] = append(l.approved[staffID], [2]time.Time{s, e})
		switch {
		case !s.After(today) && !today.After(e):
			if cur, had := l.awayNow[staffID]; !had || e.After(cur) {
				l.awayNow[staffID] = e
			}
		case s.After(today):
			if cur, had := l.nextAway[staffID]; !had || s.Before(cur) {
				l.nextAway[staffID] = s
			}
		}
	}
	return l, rows.Err()
}

// band is one officer's Team Targets reading (_target_bands).
type band struct{ fyStatus, fyTone, fyText, monthStatus string }

// readBands is _target_bands. targets.ErrHandOn passes the reader on.
func readBands(ctx context.Context, db schooldirectory.Querier, members []member, fy string, today time.Time, l leave) (map[string]band, error) {
	people := []targets.Person{}
	for _, m := range members {
		people = append(people, targets.Person{UserID: m.userID, StaffID: m.staffID})
	}
	roster, err := targets.Prepare(ctx, db, people, fy, l.approved)
	if err != nil {
		return nil, err
	}
	current := targets.MonthOfFY(today, fy) != 0
	out := map[string]band{}
	for _, p := range people {
		mem := roster.Member(p, today)
		cell := mem.Cells[len(mem.Cells)-1]
		text := ""
		switch {
		case cell.Status == "Not Assigned":
			text = "No targets agreed"
		case cell.DisplayPct == nil:
			text = cell.Status
		default:
			text = fmt.Sprintf("%d%% · %s", *cell.DisplayPct, cell.Status)
		}
		b := band{fyStatus: cell.Status, fyTone: cell.Tone, fyText: text}
		if current {
			b.monthStatus = mem.Status
		}
		out[p.StaffID] = b
	}
	return out, nil
}

// review is the year's agreement, the latest made (_reviews).
type review struct{ stage string }

func readReviews(ctx context.Context, db schooldirectory.Querier, members []member, fy string) (map[string]review, error) {
	rows, err := db.Query(ctx, `
SELECT staff_id, COALESCE(stage, '') FROM hr_performance_review
WHERE staff_id = ANY($1) AND fy = $2 AND review_type = 'annual_priorities' ORDER BY created_at`,
		ids(members, func(m member) string { return m.staffID }), fy)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the reviews: %w", err)
	}
	defer rows.Close()
	out := map[string]review{}
	for rows.Next() {
		var staffID, stage string
		if err := rows.Scan(&staffID, &stage); err != nil {
			return nil, fmt.Errorf("myteam: reading a review: %w", err)
		}
		out[staffID] = review{stage: stage}
	}
	return out, rows.Err()
}

// pdRequest is a development request at the supervisor's stage.
type pdRequest struct{ id, course string }

func readDevelopment(ctx context.Context, db schooldirectory.Querier, members []member) (map[string][]pdRequest, error) {
	rows, err := db.Query(ctx, `
SELECT id, staff_id, COALESCE(course_name, '') FROM pd_request WHERE staff_id = ANY($1) AND status = $2 ORDER BY id`,
		ids(members, func(m member) string { return m.staffID }), rules.PDSupervisorStatus)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the development requests: %w", err)
	}
	defer rows.Close()
	out := map[string][]pdRequest{}
	for rows.Next() {
		var r pdRequest
		var staffID string
		if err := rows.Scan(&r.id, &staffID, &r.course); err != nil {
			return nil, fmt.Errorf("myteam: reading a development request: %w", err)
		}
		out[staffID] = append(out[staffID], r)
	}
	return out, rows.Err()
}

// escalation is an open escalation an officer raised that the lead decides.
type escalation struct {
	raisedByName, subject, severity string
	createdAt                       time.Time
}

func readEscalations(ctx context.Context, db schooldirectory.Querier, p auth.Principal, members []member) (map[string][]escalation, error) {
	users := ids(members, func(m member) string { return m.userID })
	args := []any{}
	inbox, err := escalations.InboxClause(ctx, db, p, &args)
	if err != nil {
		return nil, err
	}
	if inbox == "" || len(users) == 0 {
		return map[string][]escalation{}, nil
	}
	args = append(args, users, rules.EscalationResolved)
	rows, err := db.Query(ctx, fmt.Sprintf(`
SELECT raised_by_user_id, COALESCE(raised_by_name, ''), COALESCE(subject, ''), COALESCE(severity, ''), created_at
FROM leadership_escalation WHERE %s AND raised_by_user_id = ANY($%d) AND status <> $%d ORDER BY created_at`,
		inbox, len(args)-1, len(args)), args...)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the escalations: %w", err)
	}
	defer rows.Close()
	out := map[string][]escalation{}
	for rows.Next() {
		var user string
		var e escalation
		if err := rows.Scan(&user, &e.raisedByName, &e.subject, &e.severity, &e.createdAt); err != nil {
			return nil, fmt.Errorf("myteam: reading an escalation: %w", err)
		}
		out[user] = append(out[user], e)
	}
	return out, rows.Err()
}

// countBy reads (key, count) rows.
func countBy(ctx context.Context, db schooldirectory.Querier, what, sql string, args ...any) (map[string]int, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading %s: %w", what, err)
	}
	defer rows.Close()
	out := map[string]int{}
	for rows.Next() {
		var key string
		var n int
		if err := rows.Scan(&key, &n); err != nil {
			return nil, fmt.Errorf("myteam: reading %s: %w", what, err)
		}
		out[key] = n
	}
	return out, rows.Err()
}

// coaching is an officer's latest coaching record the reader may read.
type coaching struct {
	heldOn                         *time.Time
	kind                           string
	shared, acknowledged, followUp bool
}

// readCoaching is last_coaching_by_cceo under coaching_visible_to for the
// readers My Team opens to: Admin every record, a Programme Lead the ones
// they wrote about their team, anyone else none.
func readCoaching(ctx context.Context, db schooldirectory.Querier, p auth.Principal, members []member) (map[string]coaching, error) {
	staff := ids(members, func(m member) string { return m.staffID })
	out := map[string]coaching{}
	if len(staff) == 0 {
		return out, nil
	}
	visible, args := "", []any{staff}
	switch p.ActiveRole {
	case roleAdmin:
		visible = "TRUE"
	case rolePL:
		args = append(args, p.UserID)
		visible = "c.author_id = $2"
	default:
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT DISTINCT ON (c.cceo_staff_id) c.cceo_staff_id, c.held_on, COALESCE(c.kind, ''), c.shared_at IS NOT NULL, c.acknowledged_at IS NOT NULL,
       EXISTS (SELECT 1 FROM cce_cceo_coaching f WHERE f.cceo_staff_id = c.cceo_staff_id AND `+swapAlias(visible)+`
               AND f.follow_up_due IS NOT NULL AND f.follow_up_done_at IS NULL)
FROM cce_cceo_coaching c WHERE c.cceo_staff_id = ANY($1) AND `+visible+`
ORDER BY c.cceo_staff_id, c.held_on DESC, c.created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the coaching: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var staffID string
		var c coaching
		if err := rows.Scan(&staffID, &c.heldOn, &c.kind, &c.shared, &c.acknowledged, &c.followUp); err != nil {
			return nil, fmt.Errorf("myteam: reading a coaching record: %w", err)
		}
		out[staffID] = c
	}
	return out, rows.Err()
}

func swapAlias(clause string) string {
	if clause == "TRUE" {
		return clause
	}
	return "f.author_id = $2"
}

// TeamMemberIDs is team_member_ids for a lead who is not working in an
// acting appointment: the People records of the officers they line-manage
// (their own supervisees and, while they cover an absent lead, that lead's).
func TeamMemberIDs(ctx context.Context, db schooldirectory.Querier, profileID string, now time.Time) ([]string, error) {
	members, err := teamMembers(ctx, db, profileID, now)
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(members))
	for _, m := range members {
		ids = append(ids, m.staffID)
	}
	return ids, nil
}
