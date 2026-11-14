package adminops

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
)

// TeamPlansPath is Team Plans, everyone's My Plan in one read-only table.
const TeamPlansPath = "/admin-ops/team-plans"

// planRow is one activity as Team Plans reads it.
type planRow struct {
	ID, Owner, Monitor, Type, Status, Delivery, Partner, Project string
	School, SchoolID, Cluster                                    *string
	Planned                                                      *time.Time
	Reschedules                                                  int
	Salesforce, IAState, Payment                                 string
	CostMissing                                                  bool
	Updated                                                      time.Time
}

// person is _people_index's entry.
type person struct{ name, role string }

// teamPlanFilters are the query keys AdminTeamPlansService.get reads.
var teamPlanFilters = []string{"fy", "month", "week", "activity_type", "status", "district", "project", "partner", "user", "team", "role", "overdue"}

// teamPlans is team_plans_view (AdminTeamPlansService.get and
// filter_options). A week that is not a number fails the existing page, so
// it is passed on to give the same answer.
func (s *Service) teamPlans(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	q := map[string]string{}
	for _, k := range teamPlanFilters {
		q[k] = query.Get(k)
	}
	week := strings.TrimSpace(q["week"])
	weekNumber := 0
	if week != "" {
		n, err := strconv.Atoi(week)
		if err != nil {
			return nil, false, nil
		}
		weekNumber = n
	}
	now := s.now()
	fy := q["fy"]
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	args := []any{fy, rules.TeamPlans.TerminalStatuses}
	where := `a.deleted_at IS NULL AND a.fy = $1 AND NOT (a.status = ANY($2))`
	add := func(clause string, v any) {
		args = append(args, v)
		where += fmt.Sprintf(" AND "+clause, len(args))
	}
	if p.ActiveRole != "Admin" {
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
		if err != nil {
			return nil, true, fmt.Errorf("adminops: resolving the reader's scope: %w", err)
		}
		if scope.CountryScope && scope.Country != "" {
			args = append(args, scope.Country)
			where += " AND " + schoolprofile.ActivityInCountry(len(args))
		}
	}
	if m := strings.TrimSpace(q["month"]); m != "" {
		add("a.planned_month = $%d", m)
	}
	if week != "" {
		add("a.planned_week = $%d", weekNumber)
	}
	for key, column := range map[string]string{"activity_type": "a.activity_type", "status": "a.status",
		"district": "s.district_id", "project": "a.project_id", "partner": "a.assigned_partner_id"} {
		if v := strings.TrimSpace(q[key]); v != "" {
			add(column+" = $%d", v)
		}
	}
	if u := strings.TrimSpace(q["user"]); u != "" {
		args = append(args, u)
		where += fmt.Sprintf(" AND (a.responsible_staff_id = $%[1]d OR a.monitored_by_staff_id = $%[1]d)", len(args))
	}
	if team := strings.TrimSpace(q["team"]); team != "" {
		args = append(args, team)
		where += fmt.Sprintf(` AND a.responsible_staff_id IN (SELECT $%[1]d::varchar UNION SELECT l.supervisee_id FROM staff_supervisor_assignment l WHERE l.supervisor_id = $%[1]d
  UNION SELECT sp.user_id FROM staff_supervisor_assignment l JOIN staff_profile sp ON sp.id = l.supervisee_id WHERE l.supervisor_id = $%[1]d AND sp.user_id IS NOT NULL)`, len(args))
	}
	args = append(args, rules.TeamPlans.ReadLimit)
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''), a.activity_type, a.status,
  COALESCE(a.delivery_type, ''), COALESCE(a.assigned_partner_id, ''), COALESCE(a.project_id, ''),
  s.name, s.id, cl.name, a.planned_date, COALESCE(a.reschedule_count, 0), COALESCE(a.salesforce_activity_id, ''),
  COALESCE(a.ia_verification_status, ''), COALESCE(a.payment_status, ''), a.cost_missing, a.updated_at
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE `+where+fmt.Sprintf(`
ORDER BY a.planned_date, a.planned_month, a.planned_week, a.id LIMIT $%d`, len(args)), args...)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the plans: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (planRow, error) {
		var x planRow
		err := r.Scan(&x.ID, &x.Owner, &x.Monitor, &x.Type, &x.Status, &x.Delivery, &x.Partner, &x.Project,
			&x.School, &x.SchoolID, &x.Cluster, &x.Planned, &x.Reschedules, &x.Salesforce,
			&x.IAState, &x.Payment, &x.CostMissing, &x.Updated)
		return x, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the plans: %w", err)
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	ids := make([]string, len(list))
	for i, x := range list {
		ids[i] = x.ID
	}
	next, err := todos.NextActions(ctx, s.db, ids, today)
	if err != nil {
		return nil, true, err
	}
	people, partners, err := s.planIndexes(ctx)
	if err != nil {
		return nil, true, err
	}
	options, err := s.teamPlanOptions(ctx, fy)
	if err != nil {
		return nil, true, err
	}
	return teamPlansPage(list, next, people, partners, options, q, fy, today, query), true, nil
}

// planIndexes are _people_index (live People records by profile and account
// id) and _partner_index.
func (s *Service) planIndexes(ctx context.Context) (map[string]person, map[string]string, error) {
	people := map[string]person{}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), sp.id), COALESCE(u.active_role, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL`)
	if err != nil {
		return nil, nil, fmt.Errorf("adminops: reading the people: %w", err)
	}
	for rows.Next() {
		var id, user, name, role string
		if err := rows.Scan(&id, &user, &name, &role); err != nil {
			rows.Close()
			return nil, nil, fmt.Errorf("adminops: reading the people: %w", err)
		}
		people[id] = person{name, role}
		if user != "" {
			people[user] = person{name, role}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("adminops: reading the people: %w", err)
	}
	partners := map[string]string{}
	rows, err = s.db.Query(ctx, `SELECT id, name FROM partner WHERE deleted_at IS NULL`)
	if err != nil {
		return nil, nil, fmt.Errorf("adminops: reading the partners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, nil, fmt.Errorf("adminops: reading the partners: %w", err)
		}
		partners[id] = name
	}
	return people, partners, rows.Err()
}

// planOptions is filter_options: the FY's activity types and statuses (every
// plan, whoever reads it), the live staff's roles and every district.
type planOptions struct {
	types, statuses, roles []string
	districts              [][2]string
}

func (s *Service) teamPlanOptions(ctx context.Context, fy string) (planOptions, error) {
	var o planOptions
	strs := func(sql string, args ...any) ([]string, error) {
		rows, err := s.db.Query(ctx, sql, args...)
		if err != nil {
			return nil, err
		}
		return pgx.CollectRows(rows, pgx.RowTo[string])
	}
	var err error
	if o.types, err = strs(`SELECT DISTINCT activity_type FROM activity WHERE deleted_at IS NULL AND fy = $1 AND NOT (status = ANY($2)) AND activity_type <> '' ORDER BY 1`, fy, rules.TeamPlans.TerminalStatuses); err != nil {
		return o, fmt.Errorf("adminops: reading the plan's types: %w", err)
	}
	if o.statuses, err = strs(`SELECT DISTINCT status FROM activity WHERE deleted_at IS NULL AND fy = $1 AND NOT (status = ANY($2)) AND status <> '' ORDER BY 1`, fy, rules.TeamPlans.TerminalStatuses); err != nil {
		return o, fmt.Errorf("adminops: reading the plan's statuses: %w", err)
	}
	if o.roles, err = strs(`SELECT DISTINCT u.active_role FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL AND COALESCE(u.active_role, '') <> '' ORDER BY 1`); err != nil {
		return o, fmt.Errorf("adminops: reading the roles: %w", err)
	}
	// ORDER BY 1 sorts in the database's collation; sorted() in code points.
	slices.Sort(o.types)
	slices.Sort(o.statuses)
	slices.Sort(o.roles)
	rows, err := s.db.Query(ctx, `SELECT id, name FROM district ORDER BY name`)
	if err != nil {
		return o, fmt.Errorf("adminops: reading the districts: %w", err)
	}
	o.districts, err = pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
		var d [2]string
		return d, r.Scan(&d[0], &d[1])
	})
	if err != nil {
		return o, fmt.Errorf("adminops: reading the districts: %w", err)
	}
	return o, nil
}

// pyTitle is str.title(): each run of letters capitalised at its start and
// lower-cased after.
func pyTitle(s string) string {
	out := []rune{}
	prevLetter := false
	for _, r := range s {
		if unicode.IsLetter(r) {
			if prevLetter {
				out = append(out, unicode.ToLower(r))
			} else {
				out = append(out, unicode.ToUpper(r))
			}
			prevLetter = true
			continue
		}
		out = append(out, r)
		prevLetter = false
	}
	return string(out)
}

// planStatus is get_activity_status_label_and_class's words.
func planStatus(x planRow, today time.Time) string {
	switch x.Status {
	case "completed", "closed":
		return "Complete"
	case "awaiting_owner_approval":
		return "Awaiting owner approval"
	case "submitted_to_pl", "awaiting_ia_verification", "ia_verified", "accountant_confirmed":
		if x.Salesforce == "" {
			return "Activity ID Missing"
		}
		return "Complete"
	case "returned", "returned_by_pl", "returned_by_ia":
		return "Returned for Correction"
	}
	var planned *time.Time
	if x.Planned != nil {
		d := time.Date(x.Planned.Year(), x.Planned.Month(), x.Planned.Day(), 0, 0, 0, 0, time.UTC)
		planned = &d
	}
	switch {
	case planned != nil && planned.Equal(today):
		return "Due Today"
	case x.Reschedules > 0:
		return "Rescheduled"
	case planned != nil && planned.After(today) && !planned.After(today.AddDate(0, 0, 7)):
		return "This Week"
	}
	return "Scheduled"
}

// financeState is _finance_state.
func financeState(x planRow) string {
	payment := strings.TrimSpace(x.Payment)
	if payment == "" || payment == "none" {
		if x.Delivery != "partner" {
			return "No payment expected"
		}
		return "Not started"
	}
	return pyTitle(strings.ReplaceAll(payment, "_", " "))
}
