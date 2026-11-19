package hrregister

import (
	"context"
	"fmt"
	"slices"

	"github.com/jackc/pgx/v5"
)

// The case statuses employee_relations_view groups the figures by.
var (
	erClosed        = []string{"resolved", "closed"}
	erTriage        = []string{"submitted", "triage"}
	erInvestigation = []string{"investigation", "findings", "action", "appeal"}
)

// employeeRelations is employee_relations_view: the cases the reader may see
// (visible_cases: Admin every case; HR the reach's countries, a confidential
// case only when they own or investigate it; anyone else none) in the search
// (type, status, severity or country code, the owner's or the subject's
// name), the most recently changed first; and the figures over every case of
// the reach's countries, confidential ones included, so a director knows one
// exists without seeing whom it concerns. Reading the register is audited
// (Service.recordAccess) before this is asked.
func employeeRelations(ctx context.Context, in input) (register, error) {
	reg := register{
		path: "/employee-relations", primary: hrToday, title: "Employee Relations", eyebrow: "Employee relations",
		description: "Disciplinary matters, grievances, disputes and investigations across the countries you oversee. " +
			"Confidential cases show only to the people working them.",
		columns:    []string{"Case", "Country", "Severity", "Investigator", "Opened", "Status"},
		actions:    []action{{label: "Open a case", drawer: "/employee-relations/new"}},
		emptyTitle: "No employee-relations cases",
		emptyBody: "No case you may see is open. Open a case to record a disciplinary matter, grievance, dispute or " +
			"investigation.",
	}
	if err := erCaseRows(ctx, in, &reg); err != nil {
		return register{}, err
	}
	figures, err := erFigures(ctx, in)
	if err != nil {
		return register{}, err
	}
	reg.metrics = figures
	return reg, nil
}

// erVisible is visible_cases as a WHERE clause on hr_relations_case `c`.
func erVisible(in input, args []any) (string, []any) {
	role := in.principal.ActiveRole
	if role == "Admin" {
		return "TRUE", args
	}
	if !slices.Contains(rules.ERCaseRoles, role) {
		return "FALSE", args
	}
	scope, args := in.reach.byCountry("c.country", args)
	args = append(args, in.principal.UserID)
	n := len(args)
	return fmt.Sprintf("%s AND (NOT c.is_confidential OR c.case_owner_id = $%d OR c.investigator_id = $%d)", scope, n, n), args
}

func erCaseRows(ctx context.Context, in input, reg *register) error {
	visible, args := erVisible(in, nil)
	search, args := contains(in.search, args, "c.case_type", "c.status", "c.severity", "c.country", "o.name", "su.name")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT c.id, c.case_type, c.country, c.severity, c.status, su.name, iu.name,
       (COALESCE(c.opened_at, c.created_at) AT TIME ZONE 'UTC')::date::text
FROM hr_relations_case c
LEFT JOIN "user" o ON o.id = c.case_owner_id
LEFT JOIN "user" iu ON iu.id = c.investigator_id
LEFT JOIN staff_profile sp ON sp.id = c.subject_staff_id
LEFT JOIN "user" su ON su.id = sp.user_id
WHERE %s AND %s ORDER BY c.updated_at DESC`, visible, search), args...)
	if err != nil {
		return fmt.Errorf("hrregister: reading the employee-relations cases: %w", err)
	}
	type erCase struct {
		id, caseType, country, severity, status, opened string
		subject, investigator                           *string
	}
	cases, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (erCase, error) {
		var c erCase
		err := row.Scan(&c.id, &c.caseType, &c.country, &c.severity, &c.status, &c.subject, &c.investigator, &c.opened)
		return c, err
	})
	if err != nil {
		return fmt.Errorf("hrregister: reading the employee-relations cases: %w", err)
	}
	for _, c := range cases {
		concerns := "No named individual"
		if c.subject != nil {
			concerns = *c.subject
		}
		investigator := "Not named"
		if c.investigator != nil {
			investigator = dash(*c.investigator)
		}
		reg.rows = append(reg.rows, []string{
			labelOf(rules.ERCaseTypes, c.caseType) + " · " + concerns, dash(c.country),
			dash(labelOf(rules.Severities, c.severity)), investigator, dash(c.opened),
			dash(labelOf(rules.ERCaseStatuses, c.status)),
		})
		reg.rowActions = append(reg.rowActions, []action{{label: "Open case", drawer: "/employee-relations/" + c.id}})
	}
	return nil
}

func erFigures(ctx context.Context, in input) ([]metric, error) {
	scope, args := in.reach.byCountry("c.country", nil)
	args = append(args, erClosed, erTriage, erInvestigation)
	n := len(args)
	var open, triage, investigating, disciplinary, critical, resolved int
	err := in.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FILTER (WHERE c.status <> ALL($%[1]d)),
       count(*) FILTER (WHERE c.status <> ALL($%[1]d) AND c.status = ANY($%[2]d)),
       count(*) FILTER (WHERE c.status <> ALL($%[1]d) AND c.status = ANY($%[3]d)),
       count(*) FILTER (WHERE c.status <> ALL($%[1]d) AND c.case_type = 'disciplinary'),
       count(*) FILTER (WHERE c.status <> ALL($%[1]d) AND c.severity = 'critical'),
       count(*) FILTER (WHERE c.status = ANY($%[1]d))
FROM hr_relations_case c WHERE %[4]s`, n-2, n-1, n, scope), args...).
		Scan(&open, &triage, &investigating, &disciplinary, &critical, &resolved)
	if err != nil {
		return nil, fmt.Errorf("hrregister: counting the employee-relations cases: %w", err)
	}
	return []metric{
		{"Open cases", count(open), "not yet resolved", "info"},
		{"Awaiting triage", count(triage), "submitted or in restricted triage", "warning"},
		{"Under investigation", count(investigating), "investigation to appeal", "info"},
		{"Disciplinary matters", count(disciplinary), "open", "warning"},
		{"Critical", count(critical), "open and critical", "danger"},
		{"Resolved", count(resolved), "resolved or closed", "success"},
	}, nil
}
