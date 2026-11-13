package hrregister

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
)

// allCountries is a requirement that binds every country.
const allCountries = "All"

// requirementsIn is visible_requirements as a WHERE clause on
// hr_compliance_requirement `r`: every requirement for an organisation's
// reach; otherwise those for every country and the reach's own.
func (rc reach) requirementsIn(args []any) (string, []any) {
	if rc.kind == reachAll {
		return "TRUE", args
	}
	args = append(args, append([]string{allCountries}, rc.countries...))
	return fmt.Sprintf("r.country = ANY($%d)", len(args)), args
}

// complianceRegister is compliance_register_view: first the gaps (each
// active, not exited person in reach and each mandatory requirement of their
// country or every country they have no record against, by name and
// requirement), then the records of the People in reach, the most urgent
// first (expired, missing, due soon, compliant), by expiry day and name; both
// narrowed by the search.
func complianceRegister(ctx context.Context, in input) (register, error) {
	gaps, err := complianceGaps(ctx, in)
	if err != nil {
		return register{}, err
	}
	visibleSQL, args := in.reach.visible(nil)
	searchSQL, args := contains(in.search, args, "u.name", "r.name", "r.country", "c.status")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT c.id, u.name, r.name, r.country, c.expiry_date::text, vu.name, c.status
FROM hr_employee_compliance_record c JOIN staff_profile sp ON sp.id = c.staff_id JOIN "user" u ON u.id = sp.user_id
JOIN hr_compliance_requirement r ON r.id = c.requirement_id LEFT JOIN "user" vu ON vu.id = c.verified_by_id
WHERE c.staff_id IN %s AND %s
ORDER BY CASE c.status WHEN 'Expired' THEN 0 WHEN 'Missing' THEN 1 WHEN 'Due Soon' THEN 2 WHEN 'Compliant' THEN 3 ELSE 4 END,
         c.expiry_date, u.name`, visibleSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the compliance records: %w", err)
	}
	type record struct {
		id, person, requirement, country, status string
		expiry, verifier                         *string
	}
	records, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (record, error) {
		var r record
		err := row.Scan(&r.id, &r.person, &r.requirement, &r.country, &r.expiry, &r.verifier, &r.status)
		return r, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the compliance records: %w", err)
	}
	reqSQL, args := in.reach.requirementsIn(nil)
	var requirements int
	if err := in.db.QueryRow(ctx, `SELECT count(*) FROM hr_compliance_requirement r WHERE `+reqSQL, args...).Scan(&requirements); err != nil {
		return register{}, fmt.Errorf("hrregister: counting the requirements: %w", err)
	}
	reg := register{
		path: "/compliance-register", title: "Employment Compliance", eyebrow: "Policy and compliance",
		description: "Country employment-law requirements (contracts, work permits, statutory registrations) and the evidence each " +
			"employee holds. A status follows its document and expiry date.",
		columns:    []string{"Team member", "Requirement", "Country", "Expiry", "Verified by", "Status"},
		actions:    []action{{"Record evidence", "/compliance-register/new"}, {"Add a requirement", "/compliance-register/requirement"}},
		emptyTitle: "No employee compliance records yet",
		emptyBody:  "Add the employment-law requirements for your countries, then record each employee's evidence.",
	}
	for _, g := range gaps {
		reg.rows = append(reg.rows, []string{dash(g.person), dash(g.requirement), dash(g.country), "—", "No evidence on file",
			labelOf(rules.ComplianceStatuses, "Missing")})
		reg.rowActions = append(reg.rowActions, []action{{"Record", "/compliance-register/new?staff=" + g.staff + "&requirement=" + g.requirementID}})
	}
	compliant, dueSoon, remediation := 0, 0, len(gaps)
	for _, r := range records {
		switch r.status {
		case "Compliant":
			compliant++
		case "Due Soon":
			dueSoon++
		case "Missing", "Expired":
			remediation++
		}
		verifier := "Not verified"
		if r.verifier != nil {
			verifier = *r.verifier
		}
		reg.rows = append(reg.rows, []string{dash(r.person), dash(r.requirement), dash(r.country), dash(deref(r.expiry)), dash(verifier),
			dash(labelOf(rules.ComplianceStatuses, r.status))})
		reg.rowActions = append(reg.rowActions, []action{{"Update", "/compliance-register/" + r.id}})
	}
	reg.metrics = []metric{
		{"Requirements", count(requirements), "configured for your countries", "info"},
		{"Compliant", count(compliant), "evidence in date", "success"},
		{"Due soon", count(dueSoon), "expiring within 30 days", "warning"},
		{"Missing or expired", count(remediation), "requiring remediation", "danger"},
	}
	return reg, nil
}

// gap is a person with no record against a mandatory requirement.
type gap struct{ staff, person, country, requirementID, requirement string }

// complianceGaps is compliance_gaps, narrowed by the search as the view
// narrows it: a search held by the person's name, the requirement's name or
// the person's country (case-folded), or one the word "missing" holds.
func complianceGaps(ctx context.Context, in input) ([]gap, error) {
	reqSQL, args := in.reach.requirementsIn(nil)
	reachSQL, args := in.reach.profiles(args)
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
WITH requirements AS (SELECT r.id, r.name, r.country FROM hr_compliance_requirement r WHERE r.is_mandatory AND %s),
people AS (
  SELECT sp.id, u.name, sp.country FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.is_active AND %s AND NOT (sp.onboarding_state = 'exited'))
SELECT p.id, p.name, COALESCE(p.country, ''), r.id, r.name
FROM people p JOIN requirements r ON r.country = '%s' OR r.country = p.country
WHERE NOT EXISTS (SELECT 1 FROM hr_employee_compliance_record c WHERE c.staff_id = p.id AND c.requirement_id = r.id)
ORDER BY p.name, r.name`, reqSQL, reachSQL, allCountries), args...)
	if err != nil {
		return nil, fmt.Errorf("hrregister: reading the compliance gaps: %w", err)
	}
	gaps, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (gap, error) {
		var g gap
		err := row.Scan(&g.staff, &g.person, &g.country, &g.requirementID, &g.requirement)
		return g, err
	})
	if err != nil {
		return nil, fmt.Errorf("hrregister: reading the compliance gaps: %w", err)
	}
	if in.search == "" {
		return gaps, nil
	}
	needle := strings.ToLower(in.search)
	kept := []gap{}
	for _, g := range gaps {
		if strings.Contains(strings.ToLower(g.person), needle) || strings.Contains(strings.ToLower(g.requirement), needle) ||
			strings.Contains(strings.ToLower(g.country), needle) || strings.Contains("missing", needle) {
			kept = append(kept, g)
		}
	}
	return kept, nil
}
