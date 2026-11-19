package hrregister

import (
	"context"
	"fmt"
	"slices"

	"github.com/jackc/pgx/v5"
)

// liveVacancyStatuses are the vacancies still being decided or filled: each
// offers its Review drawer, and an open or pending one replacing a leaver is
// counted under Replacements.
var liveVacancyStatuses = []string{"pending_approval", "approved", "open"}

// recruitment is recruitment_view: the vacancies of the reach's countries
// whose role, department, country or status code holds the search, the
// newest first, each with its applications, and a live one with its Review
// drawer. The figures count the searched vacancies.
func recruitment(ctx context.Context, in input) (register, error) {
	scopeSQL, args := in.reach.byCountry("v.country", nil)
	searchSQL, args := contains(in.search, args, "v.role", "v.department", "v.country", "v.status")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT v.id, v.role, v.department, v.country, v.replacement_or_new_role, v.status,
  COALESCE(v.target_start_date::text, ''), (SELECT count(*) FROM hr_application a WHERE a.vacancy_id = v.id)
FROM hr_vacancy v WHERE %s AND %s ORDER BY v.created_at DESC`, scopeSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the vacancies: %w", err)
	}
	type vacancy struct {
		id, role, department, country, kind, status, start string
		applications                                       int
	}
	vacancies, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (vacancy, error) {
		var v vacancy
		err := row.Scan(&v.id, &v.role, &v.department, &v.country, &v.kind, &v.status, &v.start, &v.applications)
		return v, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the vacancies: %w", err)
	}
	reg := register{
		path: "/recruitment", title: "Recruitment & Vacancies", eyebrow: "Staffing and recruiting",
		description: "Staffing needs across the countries you oversee: new roles for growth and replacements after turnover, from request and approval to an open post.",
		columns:     []string{"Vacancy", "Country", "Type", "Applications", "Target start", "Status"},
		actions:     []action{{label: "Request a vacancy", drawer: "/recruitment/new"}},
		emptyTitle:  "No vacancies yet",
		emptyBody:   "Request a vacancy to start recruiting for a new role or to replace someone who is leaving.",
	}
	if consoleRole(in.principal.ActiveRole) {
		reg.primary = &action{label: "Candidate Pipeline", href: "/candidate-pipeline"}
	}
	open, pending, replacements, applications := 0, 0, 0, 0
	for _, v := range vacancies {
		live := slices.Contains(liveVacancyStatuses, v.status)
		switch {
		case v.status == "open":
			open++
		case v.status == "pending_approval":
			pending++
		}
		if live && v.kind == "replacement" {
			replacements++
		}
		applications += v.applications
		name := v.role
		if v.department != "" {
			name += " · " + v.department
		}
		var review []action
		if live {
			review = []action{{label: "Review", drawer: "/recruitment/" + v.id}}
		}
		reg.rows = append(reg.rows, []string{dash(name), dash(v.country), dash(labelOf(rules.VacancyTypes, v.kind)),
			count(v.applications), dash(v.start), dash(labelOf(rules.VacancyStatuses, v.status))})
		reg.rowActions = append(reg.rowActions, review)
	}
	reg.metrics = []metric{
		{"Open", count(open), "accepting candidates", "success"},
		{"Pending approval", count(pending), "awaiting a Country Director or the RVP", "warning"},
		{"Replacements", count(replacements), "open posts replacing a leaver", "info"},
		{"Applications", count(applications), "across visible vacancies", "info"},
	}
	return reg, nil
}
