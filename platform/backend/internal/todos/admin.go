package todos

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// adminRole is the Admin (EdifyRole.ADMIN).
const adminRole = "Admin"

// AdminRules are the vocabularies of the builders the Admin reaches beyond
// the officer's and the lead's (export_todos_rules.admin_rules).
type AdminRules struct {
	AccountantQueueStatuses           map[string]string  `json:"accountant_queue_statuses"`
	CountryBudget                     CountryBudgetRules `json:"country_budget"`
	CostCatalogueSettledStatuses      []string           `json:"cost_catalogue_settled_statuses"`
	BTVerificationSchedulingRoles     []string           `json:"bt_verification_scheduling_roles"`
	PolicyAwaitingPublicationStatuses []string           `json:"policy_awaiting_publication_statuses"`
	PartnerUserSetupRoles             []string           `json:"partner_user_setup_roles"`
	PartnerUserSetupPending           string             `json:"partner_user_setup_pending"`
}

// CountryBudgetRules are _country_budget_todos' desks: the country whose
// General Budget they hold, who sits at each, and the statuses each acts on.
type CountryBudgetRules struct {
	Country           string   `json:"country"`
	CDRoles           []string `json:"cd_roles"`
	RVPRoles          []string `json:"rvp_roles"`
	AccountantRoles   []string `json:"accountant_roles"`
	ReviewStatuses    []string `json:"review_statuses"`
	ReturnedStatus    string   `json:"returned_status"`
	SubmittedStatus   string   `json:"submitted_status"`
	ApprovedStatus    string   `json:"approved_status"`
	TeamRequestStatus string   `json:"team_request_status"`
}

func init() {
	for name, build := range map[string]func(context.Context, *Service, *reader) ([]todo, error){
		"_hr_exception_todos":   hrExceptionGuard,
		"_accountant_todos":     accountantGuard,
		"_country_budget_todos": countryBudgetTodos,
		"_cost_catalogue_todos": costCatalogueTodos,
		"_escalation_todos":     escalationGuard,
		"apps.partners.user_setup_todos:partner_user_setup_todos": partnerUserSetupTodos,
	} {
		register(name, build)
	}
}

// _ia_todos lists activities awaiting IA verification in the reader's
// country; for the Admin, plReviewGuard passes on any activity in that
// status (it is one of pl_review.LEAD_REVIEWABLE_STATUSES), wherever it is,
// so it stands for it. It is registered once, in ia.go.

// hrExceptionGuard stands for _hr_exception_todos, the "waiting on HR"
// group of hr.hr_exceptions: any leave or Professional Development request
// (an escalated leave, a request waiting on HR), a policy waiting to be
// reviewed or published, an onboarding plan whose probation review is due.
func hrExceptionGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM leave
UNION ALL SELECT 1 FROM pd_request
UNION ALL SELECT 1 FROM document_asset WHERE archived_at IS NULL AND status = ANY($1)
UNION ALL SELECT 1 FROM hr_onboarding_plan WHERE probation_review_date <= $2`,
		rules.Admin.PolicyAwaitingPublicationStatuses, r.today))
}

// accountantGuard stands for _accountant_todos and its settlement queues:
// any request, advance or partner work at one of the Accountant's desks
// (partner work only: both partner queues read delivery_type "partner")
// (ACCOUNTANT_QUEUE_STATUSES), and cash handed back that nobody verified.
func accountantGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	st := rules.Admin.AccountantQueueStatuses
	return passOnIf(s.exists(ctx, `SELECT 1 FROM fund_request WHERE status = $1
UNION ALL SELECT 1 FROM activity WHERE deleted_at IS NULL AND delivery_type = 'partner' AND (status = $2 OR payment_status = $3)
UNION ALL SELECT 1 FROM weekly_fund_request WHERE status = $4
UNION ALL SELECT 1 FROM advance_request WHERE status = ANY($5)
UNION ALL SELECT 1 FROM advance_request WHERE returned_amount > 0 AND return_verified_at IS NULL`,
		st["monthly_request"], st["partner_clearance"], st["partner_payable"], st["weekly_request"],
		[]string{st["accountability"], st["reimbursement"], st["disbursed"]}))
}

// countryBudgetTodos is _country_budget_todos: the General Budget's desks.
// The Country Director's (this month's budget to review, budgets and FY
// work plans the RVP returned, team monthly requests), the RVP's (budgets
// submitted to them) and the Accountant's (approved budgets to prepare); the
// Admin sits at all three.
func countryBudgetTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	cb := rules.Admin.CountryBudget
	var out []todo
	if contains(cb.CDRoles, r.role) {
		rows, err := s.cdBudgetRows(ctx, r)
		if err != nil {
			return nil, err
		}
		out = append(out, rows...)
	}
	for _, desk := range []struct {
		roles                   []string
		status, title, category string
		actionLabel, actionURL  string
	}{
		{cb.RVPRoles, cb.SubmittedStatus, "Review General Budget", "Budget Approval", "Review", "/country-budget"},
		{cb.AccountantRoles, cb.ApprovedStatus, "Prepare Monthly Disbursement Queue", "Finance", "Prepare", "/disbursements"},
	} {
		if !contains(desk.roles, r.role) {
			continue
		}
		keys, err := s.strings(ctx, `SELECT month_key FROM monthly_work_plan_budget WHERE country_id = $1 AND status = $2
ORDER BY month_key DESC LIMIT 5`, budgetCountry(r), desk.status)
		if err != nil {
			return nil, err
		}
		for _, key := range keys {
			out = append(out, todo{Title: desk.title, Category: desk.category, Priority: "high", StatusKey: "waiting_me",
				Actionable: true, Linked: "General Budget · " + key, ActionLabel: desk.actionLabel,
				ActionURL: desk.actionURL, Shape: desk.actionURL})
		}
	}
	return out, nil
}

// cdBudgetRows are the Country Director's desk of _country_budget_todos.
func (s *Service) cdBudgetRows(ctx context.Context, r *reader) ([]todo, error) {
	cb := rules.Admin.CountryBudget
	var out []todo
	// The month is date.today()'s; .first() of an unordered queryset is the
	// lowest id.
	month := fmt.Sprintf("%d-%02d", r.today.Year(), int(r.today.Month()))
	current, err := s.strings(ctx, `SELECT month_key FROM monthly_work_plan_budget
WHERE country_id = $1 AND month_key = $2 AND status = ANY($3) ORDER BY id ASC LIMIT 1`, budgetCountry(r), month, cb.ReviewStatuses)
	if err != nil {
		return nil, err
	}
	for _, key := range current {
		out = append(out, todo{Title: "Review " + key + " General Budget", Category: "Budget Approval", Priority: "medium",
			StatusKey: "waiting_me", Actionable: true, Linked: "General Budget · " + key, ActionLabel: "Review",
			ActionURL: "/country-budget", Shape: "/country-budget"})
	}
	returned, err := s.strings(ctx, `SELECT month_key FROM monthly_work_plan_budget WHERE country_id = $1 AND status = $2
ORDER BY month_key DESC LIMIT 5`, budgetCountry(r), cb.ReturnedStatus)
	if err != nil {
		return nil, err
	}
	for _, key := range returned {
		out = append(out, todo{Title: "Fix Returned General Budget", Category: "Budget Approval", Priority: "critical",
			StatusKey: "returned", Actionable: true, Linked: "General Budget · " + key, ActionLabel: "Fix",
			ActionURL: "/country-budget", Shape: "/country-budget", Due: &r.today})
	}
	fys, err := s.strings(ctx, `SELECT fy FROM country_annual_budget WHERE country_id = $1 AND status = $2
ORDER BY fy DESC LIMIT 3`, budgetCountry(r), cb.ReturnedStatus)
	if err != nil {
		return nil, err
	}
	for _, fy := range fys {
		out = append(out, todo{Title: "Fix Returned FY" + fy + " Work Plan", Category: "Budget Approval", Priority: "critical",
			StatusKey: "returned", Actionable: true, Linked: "FY Work Plan · " + fy, ActionLabel: "Fix",
			ActionURL: "/work-plan?view=fy", Shape: "/work-plan?view=fy", Due: &r.today})
	}
	rows, err := s.db.Query(ctx, `SELECT period_key FROM fund_request WHERE status = $1 ORDER BY created_at DESC LIMIT 10`,
		cb.TeamRequestStatus)
	if err != nil {
		return nil, err
	}
	periods, err := pgx.CollectRows(rows, pgx.RowTo[*string])
	if err != nil {
		return nil, err
	}
	for _, period := range periods {
		out = append(out, todo{Title: "Approve Team Monthly Request", Category: "Budget Approval", Priority: "high",
			StatusKey: "waiting_me", Actionable: true, Linked: "Team request · " + pyStr(period), ActionLabel: "Review",
			ActionURL: "/budget", Shape: "/budget", Due: &r.today})
	}
	return out, nil
}

// costCatalogueTodos is _cost_catalogue_todos: one row while any scheduled,
// unsettled activity is missing a rate.
func costCatalogueTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var n int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM activity WHERE deleted_at IS NULL AND cost_missing
  AND scheduled_date IS NOT NULL AND NOT (status IS NOT NULL AND status = ANY($1))`,
		rules.Admin.CostCatalogueSettledStatuses).Scan(&n); err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	return []todo{{Title: "Set Missing Cost Catalogue Rates", Category: "Finance", Priority: "high", StatusKey: "blocked",
		Actionable: true, Linked: "Cost Catalogue", ActionLabel: "Set Rates", ActionURL: "/cost-settings",
		Shape: "/cost-settings", Due: &r.today}}, nil
}

// partnerUserSetupTodos is partners.user_setup_todos: one row for the user
// administrator while any partner organisation waits for its logins.
func partnerUserSetupTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if !contains(rules.Admin.PartnerUserSetupRoles, r.role) {
		// The existing may_manage_partner_users also lets any superuser of
		// another role through; Go decides by role alone (owner, 2026-11-13:
		// "Can you fix those from the go side").
		return nil, nil
	}
	pending := rules.Admin.PartnerUserSetupPending
	names, err := s.strings(ctx, `SELECT name FROM partner WHERE deleted_at IS NULL AND user_setup_status = $1
ORDER BY created_at ASC LIMIT 4`, pending)
	if err != nil || len(names) == 0 {
		return nil, err
	}
	total := len(names)
	if total >= 4 {
		if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM partner WHERE deleted_at IS NULL AND user_setup_status = $1`,
			pending).Scan(&total); err != nil {
			return nil, err
		}
	}
	return []todo{{Title: "Configure Partner Users", Category: "Partners", Priority: "high", StatusKey: "waiting_me",
		Actionable: true, Linked: plural(total, "organisation"), ActionLabel: "Set up logins",
		ActionURL: "/admin-panel/users#partner-directory-title", Shape: "/admin-panel/users#partner-directory-title",
		Due: &r.today}}, nil
}

// loanVerificationsToSchedule is the scheduling desk of
// _business_transformation_todos (BT_VERIFICATION_SCHEDULING_ROLES): every
// verification of a loan the reader may inspect (scoped_loans: the
// country's schools) with no visit planned yet, at most thirty, soonest
// first.
func loanVerificationsToSchedule(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.scope.Country != "" {
		// A country-bound lens reads school_in_country_q, not ported here.
		return nil, errPassOn
	}
	rows, err := s.db.Query(ctx, `
SELECT r.due_date, s.name, s.school_id, m.name
FROM bt_loan_verification_requirement r INNER JOIN bt_mfi_loan l ON l.id = r.loan_id
  INNER JOIN school s ON s.id = l.school_id INNER JOIN bt_mfi_organization m ON m.id = l.mfi_id
WHERE r.loan_id IN (SELECT id FROM bt_mfi_loan WHERE deleted_at IS NULL
    AND school_id IN (SELECT id FROM school WHERE deleted_at IS NULL))
  AND r.activity_id IS NULL AND r.status = ANY($1)
ORDER BY r.due_date ASC LIMIT 30`, rules.LoanFieldVerificationStates)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var due time.Time
		var name, code, mfi *string
		err := row.Scan(&due, &name, &code, &mfi)
		t := todo{Title: "Schedule Loan-Use Verification", Category: "Business Transformation", Priority: "high",
			StatusKey: "waiting_me", Actionable: true, Linked: pyStr(name) + " · " + pyStr(mfi), ActionLabel: "Plan Visit",
			ActionURL: "/schools/" + pyStr(code) + "#school-bt-title", Shape: "/schools/{code}#school-bt-title", Due: dateOf(due)}
		if dateOf(due).Before(r.today) {
			t.Priority, t.StatusKey = "critical", "overdue"
		}
		return t, err
	})
}

// strings reads one text column.
func (s *Service) strings(ctx context.Context, sql string, args ...any) ([]string, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// budgetCountry is the country whose General Budget the reader's desks hold:
// the reader's own. The existing builder reads one hard-coded country for
// every desk; Go falls back to it only for a reader with no country (the
// Admin) (owner, 2026-11-13: "Can you fix those from the go side").
func budgetCountry(r *reader) string {
	if c := strings.TrimSpace(r.scope.Country); c != "" {
		return c
	}
	return rules.Admin.CountryBudget.Country
}
