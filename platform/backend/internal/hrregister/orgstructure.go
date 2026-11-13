package hrregister

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// topRoles report outside the platform: no line recorded is no gap for them.
var topRoles = []string{"CountryDirector", "RegionalVicePresident", "Admin"}

// person is one People record the Organization Structure lists.
type person struct {
	id, name, title, activeRole, department, country, state string
	lines                                                   []string
	reports                                                 int
}

// searched is _search_profiles: a name, email, title, department or country
// holding the search, as a WHERE clause on staff_profile `sp` and user `u`.
func searched(q string, args []any) (string, []any) {
	if q == "" {
		return "TRUE", args
	}
	args = append(args, closedschools.LikeContains(q))
	n := len(args)
	parts := []string{}
	for _, col := range []string{"u.name", "u.email", "sp.title", "sp.department", "sp.country"} {
		parts = append(parts, fmt.Sprintf("UPPER(%s::text) LIKE UPPER($%d)", col, n))
	}
	return "(" + strings.Join(parts, " OR ") + ")", args
}

// orgStructure is org_structure_view: the People records in reach and
// search, not exited, by department and name, each with whom they report to
// and how many report to them.
func orgStructure(ctx context.Context, db schooldirectory.Querier, r reach, query url.Values) (register, error) {
	reachSQL, args := r.profiles(nil)
	searchSQL, args := searched(closedschools.StripSpace(query.Get("q")), args)
	rows, err := db.Query(ctx, fmt.Sprintf(`
WITH people AS (
  SELECT sp.id, u.name, COALESCE(sp.title, '') AS title, COALESCE(u.active_role, '') AS active_role,
         sp.department, COALESCE(sp.country, '') AS country, sp.onboarding_state
  FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND %s AND %s AND NOT (sp.onboarding_state = 'exited'))
SELECT p.id, p.name, p.title, p.active_role, COALESCE(p.department, ''), p.country, p.onboarding_state,
       COALESCE((SELECT array_agg(su.name) FROM staff_supervisor_assignment l
                 JOIN staff_profile s ON s.id = l.supervisor_id JOIN "user" su ON su.id = s.user_id
                 WHERE l.supervisee_id = p.id), '{}'),
       (SELECT count(*) FROM staff_supervisor_assignment l WHERE l.supervisor_id = p.id)
FROM people p ORDER BY p.department, p.name`, reachSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the organization structure: %w", err)
	}
	people, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (person, error) {
		var p person
		err := row.Scan(&p.id, &p.name, &p.title, &p.activeRole, &p.department, &p.country, &p.state, &p.lines, &p.reports)
		return p, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the organization structure: %w", err)
	}
	reg := register{
		path: "/org-structure", title: "Organization Structure", eyebrow: "People and staffing",
		description: "Reporting lines across the countries you oversee: who each person reports to, who reports to them, " +
			"and where a line is missing.",
		columns:    []string{"Team member", "Role", "Reports to", "Direct reports", "Department", "Country", "Lifecycle"},
		emptyTitle: "No people in this scope", emptyBody: defaultEmptyBody,
	}
	active, unlined := 0, 0
	departments := map[string]bool{}
	for _, p := range people {
		if p.state == "active" {
			active++
		}
		if p.department != "" {
			departments[p.department] = true
		}
		if len(p.lines) == 0 && !slices.Contains(topRoles, p.activeRole) {
			unlined++
		}
		lines := slices.Clone(p.lines)
		slices.Sort(lines)
		reportsTo := strings.Join(lines, ", ")
		if reportsTo == "" {
			reportsTo = "No line recorded"
		}
		role := p.title
		if role == "" {
			role = p.activeRole
		}
		reg.rows = append(reg.rows, []string{
			dash(p.name), dash(role), reportsTo, count(p.reports), dash(p.department), dash(p.country), dash(stateLabel(p.state)),
		})
	}
	unlinedTone := "success"
	if unlined > 0 {
		unlinedTone = "warning"
	}
	reg.metrics = []metric{
		{"People in scope", count(len(people)), "not exited", "info"},
		{"Active", count(active), "fully activated staff", "success"},
		{"Departments", count(len(departments)), "represented in this scope", "info"},
		{"No reporting line", count(unlined), "leave, reviews and oversight need one", unlinedTone},
	}
	return reg, nil
}

// dash is _cell's display: a dash for nothing.
func dash(v string) string {
	if v == "" {
		return "—"
	}
	return v
}

// stateLabel is get_onboarding_state_display: the state's label, else the
// state itself.
func stateLabel(state string) string {
	if l, ok := rules.OnboardingStates[state]; ok {
		return l
	}
	return state
}
