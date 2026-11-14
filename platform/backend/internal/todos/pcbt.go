package todos

import (
	"context"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Project Coordinator's and Business Transformation's builders
// (docs/migration/58-todos-pc-bto.md).

const (
	coordinatorRole = "ProjectCoordinator"
	btRole          = "BusinessTransformationOfficer"
	btCategory      = "Business Transformation"

	// btSalesforceDueDays is the days a loan submission has to be confirmed
	// in Salesforce; btSalesforceCriticalDays how long past that it turns
	// critical; btSalesforceWarnDays how early it turns high.
	btSalesforceDueDays      = 3
	btSalesforceCriticalDays = 7
	btSalesforceWarnDays     = 1
	btSalesforceRowLimit     = 40
	btVerificationRowLimit   = 30
	btGapDistrictLimit       = 20
	// learningLateDays is learning_todos._row's lateness: an oldest item more
	// than a week old is critical.
	learningLateDays     = 7
	learningRowScanLimit = 500
)

// PCBTRules are the vocabularies of those builders
// (export_todos_rules.pc_bt_rules).
type PCBTRules struct {
	EvidenceFieldRoles        []string `json:"evidence_field_roles"`
	FYPlannerRoles            []string `json:"fy_planner_roles"`
	OpenProjectStatuses       []string `json:"open_project_statuses"`
	ProjectRowLimit           int      `json:"project_row_limit"`
	ProjectScanFactor         int      `json:"project_scan_factor"`
	ProjectNotPlannedStatuses []string `json:"project_not_planned_statuses"`
	BTLoanRoles               []string `json:"bt_loan_roles"`
	BTImpactCountryBoundRoles []string `json:"bt_impact_country_bound_roles"`
	BTImpactCountryRoles      []string `json:"bt_impact_country_roles"`
	BTSalesforcePending       string   `json:"bt_salesforce_pending"`
	BTRepaymentRiskStatuses   []string `json:"bt_repayment_risk_statuses"`
	BTConcernFindings         []string `json:"bt_concern_findings"`
	BTPurposeRequested        string   `json:"bt_purpose_requested"`
	BTEligibleSchoolStatuses  []string `json:"bt_eligible_school_statuses"`
	BTDisbursedLoanStatuses   []string `json:"bt_disbursed_loan_statuses"`
	BTIAPending               string   `json:"bt_ia_pending"`
	BTIAReturned              string   `json:"bt_ia_returned"`
	BTIAVerified              string   `json:"bt_ia_verified"`
	BTLegacyPreparer          string   `json:"bt_legacy_preparer"`
}

func init() {
	register("apps.projects.portfolio_todos:project_school_planning_todos", projectSchoolPlanningTodos)
}

// projectSchoolPlanningTodos is portfolio_todos.project_school_planning_todos
// over portfolio.schools_awaiting_project_planning: the coordinator's newest
// enrolments at operating schools in their open projects with no project
// work planned there yet.
func projectSchoolPlanningTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != coordinatorRole || r.p.StaffProfileID == "" {
		return nil, nil
	}
	pc := rules.PCBT
	rows, err := s.db.Query(ctx, `
SELECT psa.project_id, psa.school_id, s.name
FROM project_school_assignment psa INNER JOIN school s ON s.id = psa.school_id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($3)
  AND psa.project_id IN (SELECT p.id FROM project p WHERE p.deleted_at IS NULL AND p.status = ANY($2)
    AND (p.manager_staff_id = $1 OR EXISTS (SELECT 1 FROM project_staff_assignment a
      WHERE a.project_id = p.id AND a.staff_id = $1 AND a.is_active)))
ORDER BY psa.created_at DESC LIMIT $4`, r.p.StaffProfileID, pc.OpenProjectStatuses, rules.OperatingStatuses,
		pc.ProjectRowLimit*pc.ProjectScanFactor)
	if err != nil {
		return nil, err
	}
	type enrolment struct{ project, school, name string }
	enrolled, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (enrolment, error) {
		var e enrolment
		var name *string
		err := row.Scan(&e.project, &e.school, &name)
		e.name = pyStr(name)
		return e, err
	})
	if err != nil || len(enrolled) == 0 {
		return nil, err
	}
	var projects, schools []string
	for _, e := range enrolled {
		projects = append(projects, e.project)
		schools = append(schools, e.school)
	}
	rows, err = s.db.Query(ctx, `SELECT project_id, school_id FROM activity
WHERE project_id = ANY($1) AND school_id = ANY($2) AND deleted_at IS NULL
  AND NOT (status IS NOT NULL AND status = ANY($3))`, projects, schools, pc.ProjectNotPlannedStatuses)
	if err != nil {
		return nil, err
	}
	planned := map[[2]string]bool{}
	if _, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (struct{}, error) {
		var project, school string
		err := row.Scan(&project, &school)
		planned[[2]string{project, school}] = true
		return struct{}{}, err
	}); err != nil {
		return nil, err
	}
	var out []todo
	for _, e := range enrolled {
		if len(out) == pc.ProjectRowLimit {
			break
		}
		if planned[[2]string{e.project, e.school}] {
			continue
		}
		out = append(out, todo{Title: "Plan Activities for Newly Added Project School", Category: "Projects",
			Priority: "medium", StatusKey: "waiting_me", Actionable: true, Linked: e.name, ActionLabel: "Plan project work",
			ActionURL: "/projects/planning?project=" + e.project, Shape: "/projects/planning?project={id}", Due: &r.today})
	}
	return out, nil
}

// btLoanSchools is the schools bt_services.scoped_loans reads for a
// Business Transformation officer (a country role): the country's schools.
func (s *Service) btLoanSchools(ctx context.Context, r *reader) ([]string, error) {
	if !contains(rules.PCBT.BTLoanRoles, r.role) || !r.scope.CountryScope {
		return nil, errPassOn
	}
	return schooldirectory.CountrySchoolIDs(ctx, s.db, r.scope.Country)
}

// btLoanScope is the loans of scoped_loans over those schools.
const btLoanScope = `SELECT id FROM bt_mfi_loan WHERE deleted_at IS NULL AND school_id = ANY($1)`

// btOfficerTodos is _business_transformation_todos for a Business
// Transformation officer: pending Salesforce confirmations and loan-use
// verification visits to schedule, and the geographic financing gap.
// Repayment risk, loan-use concerns and new loan purposes pass the reader on.
func btOfficerTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	schools, err := s.btLoanSchools(ctx, r)
	if err != nil {
		return nil, err
	}
	if found, err := btOfficerGuard(ctx, s, schools); err != nil || found {
		return passOnIf(found, err)
	}
	out, err := btSalesforceTodos(ctx, s, r, schools)
	if err != nil {
		return nil, err
	}
	more, err := btVerificationTodos(ctx, s, r, schools)
	if err != nil {
		return nil, err
	}
	out = append(out, more...)
	gap, err := btGeographyGap(ctx, s, r)
	return append(out, gap...), err
}

// btOfficerGuard is whether the sections Go does not build have rows.
func btOfficerGuard(ctx context.Context, s *Service, schools []string) (bool, error) {
	pc := rules.PCBT
	return s.exists(ctx, `
SELECT 1 FROM bt_repayment_snapshot WHERE loan_id IN (`+btLoanScope+`) AND status = ANY($2)
UNION ALL SELECT 1 FROM bt_loan_use_result u INNER JOIN bt_loan_verification_requirement q ON q.id = u.requirement_id
  WHERE q.loan_id IN (`+btLoanScope+`) AND u.finding = ANY($3) AND u.concern_reviewed_at IS NULL
UNION ALL SELECT 1 FROM bt_loan_purpose_proposal WHERE status = $4`,
		schools, pc.BTRepaymentRiskStatuses, pc.BTConcernFindings, pc.BTPurposeRequested)
}

// btGeographyGap is the one "Review Geographic Financing Gap" row: the
// districts (first twenty by region and name) with operating schools and
// none financed, six of them named.
func btGeographyGap(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	pc := rules.PCBT
	rows, err := s.db.Query(ctx, `
SELECT d.name, (SELECT COUNT(DISTINCT s.id) FROM school s
  WHERE s.district_id = d.id AND s.deleted_at IS NULL AND s.operational_status = ANY($1))
FROM district d INNER JOIN region g ON g.id = d.region_id
WHERE EXISTS (SELECT 1 FROM school s WHERE s.district_id = d.id AND s.deleted_at IS NULL AND s.operational_status = ANY($1))
  AND NOT EXISTS (SELECT 1 FROM school s INNER JOIN bt_mfi_loan l ON l.school_id = s.id
    WHERE s.district_id = d.id AND s.deleted_at IS NULL AND l.status = ANY($2))
ORDER BY g.name ASC, d.name ASC LIMIT $3`, pc.BTEligibleSchoolStatuses, pc.BTDisbursedLoanStatuses, btGapDistrictLimit)
	if err != nil {
		return nil, err
	}
	type district struct {
		name    string
		schools int
	}
	gaps, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (district, error) {
		var d district
		return d, row.Scan(&d.name, &d.schools)
	})
	if err != nil || len(gaps) == 0 {
		return nil, err
	}
	schools := 0
	for _, d := range gaps {
		schools += d.schools
	}
	return []todo{{Title: "Review Geographic Financing Gap", Category: btCategory, Priority: "medium",
		StatusKey: "waiting_me", Actionable: true, Linked: thousands(schools) + " eligible schools",
		ActionLabel: "Review coverage", ActionURL: "/business-transformation", Shape: "/business-transformation",
		Due: &r.today}}, nil
}

// thousands is Python's f"{n:,}".
func thousands(n int) string {
	digits := strconv.Itoa(n)
	for i := len(digits) - 3; i > 0; i -= 3 {
		digits = digits[:i] + "," + digits[i:]
	}
	return digits
}

// btSalesforceTodos is the officer's "Confirm loan in Salesforce" rows: due
// three days after submission (Kampala's day; the existing builder takes
// the UTC day), critical a week past that.
func btSalesforceTodos(ctx context.Context, s *Service, r *reader, schools []string) ([]todo, error) {
	rows, err := s.db.Query(ctx, `
SELECT l.id, l.submitted_at, l.created_at, m.name, p.label
FROM bt_mfi_loan l INNER JOIN bt_mfi_organization m ON m.id = l.mfi_id INNER JOIN bt_loan_purpose p ON p.id = l.purpose_id
WHERE l.deleted_at IS NULL AND l.school_id = ANY($1) AND l.salesforce_status = $2
ORDER BY l.submitted_at ASC, l.created_at ASC LIMIT $3`, schools, rules.PCBT.BTSalesforcePending, btSalesforceRowLimit)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, mfi, purpose string
		var submittedAt *time.Time
		var createdAt time.Time
		if err := row.Scan(&id, &submittedAt, &createdAt, &mfi, &purpose); err != nil {
			return todo{}, err
		}
		at := createdAt
		if submittedAt != nil {
			at = *submittedAt
		}
		return salesforceRow(id, mfi, purpose, localDate(at), r.today), nil
	})
}

func salesforceRow(id, mfi, purpose string, submitted, today time.Time) todo {
	day := 24 * time.Hour
	due := submitted.AddDate(0, 0, btSalesforceDueDays)
	age := int(today.Sub(submitted) / day)
	if age < 0 {
		age = 0
	}
	priority := "medium"
	switch {
	case today.After(due.AddDate(0, 0, btSalesforceCriticalDays)):
		priority = "critical"
	case !today.Before(due.AddDate(0, 0, -btSalesforceWarnDays)):
		priority = "high"
	}
	status := "waiting_me"
	if today.After(due) {
		status = "overdue"
	}
	return todo{Title: "Confirm loan in Salesforce", Category: btCategory, Priority: priority, StatusKey: status,
		Actionable: true, Linked: mfi + " · " + purpose + " · " + strconv.Itoa(age) + " days old", ActionLabel: "Complete",
		ActionURL: "/loans?open=" + id + "#loan-register-title", Shape: "/loans?open={id}#loan-register-title", Due: &due}
}

// btVerificationTodos is the officer's "Schedule Loan-Use Verification"
// rows: requirements with no visit that need scheduling or are overdue.
func btVerificationTodos(ctx context.Context, s *Service, r *reader, schools []string) ([]todo, error) {
	rows, err := s.db.Query(ctx, `
SELECT q.due_date, s.name, s.school_id, m.name
FROM bt_loan_verification_requirement q INNER JOIN bt_mfi_loan l ON l.id = q.loan_id
  INNER JOIN school s ON s.id = l.school_id INNER JOIN bt_mfi_organization m ON m.id = l.mfi_id
WHERE q.loan_id IN (`+btLoanScope+`) AND q.activity_id IS NULL AND q.status = ANY($2)
ORDER BY q.due_date ASC LIMIT $3`, schools, rules.LoanFieldVerificationStates, btVerificationRowLimit)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var due time.Time
		var name, code *string
		var mfi string
		err := row.Scan(&due, &name, &code, &mfi)
		d := dateOf(due)
		t := todo{Title: "Schedule Loan-Use Verification", Category: btCategory, Priority: "high", StatusKey: "waiting_me",
			Actionable: true, Linked: pyStr(name) + " · " + mfi, ActionLabel: "Plan Visit",
			ActionURL: "/schools/" + pyStr(code) + "#school-bt-title", Shape: "/schools/{code}#school-bt-title", Due: d}
		if d.Before(r.today) {
			t.Priority, t.StatusKey = "critical", "overdue"
		}
		return t, err
	})
}

// learningTodos is learning_todos for a Business Transformation officer:
// loan impact conclusions due for them to prepare, and those returned to
// them. Anyone else passes on (IA and the Country Director review findings
// and verify conclusions, which Go does not build; IA's guard dispatches
// here for every other role, ia.go).
func learningTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != btRole {
		return nil, errPassOn
	}
	pc := rules.PCBT
	loans := `SELECT id FROM bt_mfi_loan WHERE deleted_at IS NULL`
	args := []any{pc.BTIAVerified, r.today, learningRowScanLimit}
	switch {
	case contains(pc.BTImpactCountryBoundRoles, r.role):
		if r.scope.CountryScope && r.scope.Country != "" {
			loans += ` AND school_id IN (SELECT s.id FROM school s INNER JOIN region g ON g.id = s.region_id WHERE g.country = $4)`
			args = append(args, r.scope.Country)
		}
	case !contains(pc.BTImpactCountryRoles, r.role):
		return nil, errPassOn
	}
	rows, err := s.db.Query(ctx, `
SELECT due_date, COALESCE(ia_status, ''), prepared_by, prepared_at, updated_at
FROM bt_loan_impact_assessment
WHERE loan_id IN (`+loans+`) AND ia_status IS DISTINCT FROM $1 AND (due_date <= $2 OR prepared_at IS NOT NULL)
ORDER BY due_date ASC LIMIT $3`, args...)
	if err != nil {
		return nil, err
	}
	type conclusion struct {
		due, updated time.Time
		status       string
		preparedBy   *string
		preparedAt   *time.Time
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (conclusion, error) {
		var c conclusion
		return c, row.Scan(&c.due, &c.status, &c.preparedBy, &c.preparedAt, &c.updated)
	})
	if err != nil {
		return nil, err
	}
	var prepare, returned []time.Time
	for _, c := range list {
		due := *dateOf(c.due)
		unprepared := c.preparedAt == nil || c.preparedBy == nil || *c.preparedBy == "" || *c.preparedBy == pc.BTLegacyPreparer
		switch {
		case c.status == pc.BTIAPending && unprepared && !due.After(r.today):
			prepare = append(prepare, due)
		case c.status == pc.BTIAReturned && c.preparedBy != nil && *c.preparedBy == r.p.UserID:
			local := c.updated.In(zone)
			returned = append(returned, time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC))
		}
	}
	var out []todo
	if len(prepare) > 0 {
		out = append(out, learningRow("Prepare "+plural(len(prepare), "loan impact conclusion"),
			"Prepare Conclusions", prepare, r.today))
	}
	if len(returned) > 0 {
		out = append(out, learningRow("Correct "+plural(len(returned), "loan impact conclusion")+" returned to you",
			"Correct Conclusions", returned, r.today))
	}
	return out, nil
}

// learningRow is learning_todos._row for one of the officer's queues.
func learningRow(title, action string, days []time.Time, today time.Time) todo {
	oldest := days[0]
	for _, d := range days[1:] {
		if d.Before(oldest) {
			oldest = d
		}
	}
	t := todo{Title: title, Category: btCategory, Priority: "high", StatusKey: "waiting_me", Actionable: true,
		Linked: strconv.Itoa(len(days)) + " waiting", ActionLabel: action,
		ActionURL: "/business-transformation/impact-reports", Shape: "/business-transformation/impact-reports", Due: &oldest}
	if int(today.Sub(oldest)/(24*time.Hour)) > learningLateDays {
		t.Priority, t.StatusKey = "critical", "overdue"
	}
	return t
}
