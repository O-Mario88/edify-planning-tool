package hrregister

import (
	"context"
	"fmt"
	"math"

	"github.com/jackc/pgx/v5"
)

// hrAnalytics is _hr_analytics_workspace on its own page (/hr-analytics):
// the People records in reach and in the search, exited ones too, grouped by
// country and department (a department stored as none and one stored as ""
// are two groups, both "Unassigned", as the view groups them), with the
// headcount, the active, the pending and the activation rate; figures for
// the people, their countries, their reviews not yet completed or closed and
// their missing or expired compliance evidence.
func hrAnalytics(ctx context.Context, in input) (register, error) {
	reachSQL, args := in.reach.profiles(nil)
	searchSQL, args := searched(in.search, args)
	people := fmt.Sprintf(`SELECT sp.id, sp.country, sp.department, sp.onboarding_state FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND %s AND %s`, reachSQL, searchSQL)
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT p.country, COALESCE(p.department, ''), count(*), count(*) FILTER (WHERE p.onboarding_state = 'active'),
       count(*) FILTER (WHERE p.onboarding_state = 'pending')
FROM (%s) p GROUP BY p.country, p.department ORDER BY p.country, p.department`, people), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the workforce groups: %w", err)
	}
	type group struct {
		country, department     string
		headcount, active, pend int
	}
	groups, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (group, error) {
		var g group
		err := row.Scan(&g.country, &g.department, &g.headcount, &g.active, &g.pend)
		return g, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the workforce groups: %w", err)
	}
	var headcount, countries, reviewsDue, gaps int
	if err := in.db.QueryRow(ctx, fmt.Sprintf(`
WITH p AS (%s)
SELECT (SELECT count(*) FROM p), (SELECT count(DISTINCT country) + CASE WHEN bool_or(country IS NULL) THEN 1 ELSE 0 END FROM p),
       (SELECT count(*) FROM hr_performance_review r WHERE r.staff_id IN (SELECT id FROM p) AND NOT (r.status = ANY('{Completed,Closed}'))),
       (SELECT count(*) FROM hr_employee_compliance_record c WHERE c.staff_id IN (SELECT id FROM p) AND c.status = ANY('{Missing,Expired}'))`,
		people), args...).Scan(&headcount, &countries, &reviewsDue, &gaps); err != nil {
		return register{}, fmt.Errorf("hrregister: reading the workforce figures: %w", err)
	}
	reg := register{
		path: "/hr-analytics", title: "HR Analytics & Workforce Insights", eyebrow: "Human Capital Operations",
		description: "Live workforce, review, and compliance signals computed from current operational records. Unsupported " +
			"demographic and salary-correlation claims are intentionally excluded.",
		columns:    []string{"Country", "Department", "Headcount", "Active", "Pending", "Activation rate"},
		emptyTitle: "No workforce analytics in this scope",
		emptyBody:  defaultEmptyBody,
	}
	for _, g := range groups {
		department := g.department
		if department == "" {
			department = "Unassigned"
		}
		rate := 0
		if g.headcount > 0 {
			rate = int(math.RoundToEven(float64(g.active) / float64(g.headcount) * 100))
		}
		reg.rows = append(reg.rows, []string{dash(g.country), department, count(g.headcount), count(g.active), count(g.pend),
			fmt.Sprintf("%d%%", rate)})
	}
	reg.metrics = []metric{
		{"Headcount", count(headcount), "people in scope", "info"},
		{"Countries", count(countries), "operating footprint", "info"},
		{"Reviews due", count(reviewsDue), "open review workload", "warning"},
		{"Compliance gaps", count(gaps), "missing or expired evidence", "danger"},
	}
	return reg, nil
}
