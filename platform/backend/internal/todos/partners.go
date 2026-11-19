package todos

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
)

// The delivery partners' and the lending partners' own rows: a partner's
// assignments awaiting their decision (_partner_assignment_todos) and a
// lending partner's loan records Salesforce returned (the MFI section of
// _business_transformation_todos).

const (
	mfiAdminRole   = "MfiPartnerAdmin"
	mfiOfficerRole = "MfiLoanOfficer"
	// intakeLimit is how many assignments the queue lists.
	intakeLimit = 40
	// intakeLateDays is the age past which an assignment is high priority.
	intakeLateDays = 5
	// mfiReturnedLimit is how many returned loan records the queue lists.
	mfiReturnedLimit = 30
	// btPortfolioPage is where the lending section's other rows link.
	btPortfolioPage = "/business-transformation"
)

// partnerScope is the scope resolve_user_scope gives a partner login: the
// organisation it acts as (resolve_partner_ids) and the schools that
// organisation holds (its assignments, released ones left out). A partner
// owns no school record, so the direct portfolio stays empty.
func (s *Service) partnerScope(ctx context.Context, r *reader) error {
	if !contains(rules.PartnerScopeRoles, r.role) {
		return nil
	}
	partners, err := partnerassigned.PartnerIDs(ctx, s.db, r.p)
	if err != nil {
		return err
	}
	r.partners = partners
	if len(partners) == 0 {
		return nil
	}
	schools, err := s.strings(ctx, `SELECT DISTINCT school_id FROM partner_assignment
WHERE partner_id = ANY($1) AND school_id IS NOT NULL AND NOT (status = ANY($2)) ORDER BY school_id`,
		partners, rules.PartnerReleasedStatuses)
	if err != nil {
		return fmt.Errorf("todos: reading the partner's schools: %w", err)
	}
	r.scope.SchoolIDs = schools
	return nil
}

// partnerAssignmentTodos is _partner_assignment_todos: each assignment
// awaiting the partner's Schedule-or-Return decision, oldest first, forty
// of them, high priority once more than five days old.
func partnerAssignmentTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if len(r.partners) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT pa.id, pa.school_id IS NOT NULL, pa.cluster_id IS NOT NULL, s.name, c.name, pa.created_at
FROM partner_assignment pa LEFT OUTER JOIN school s ON s.id = pa.school_id LEFT OUTER JOIN cluster c ON c.id = pa.cluster_id
WHERE pa.partner_id = ANY($1) AND pa.status = ANY($2) AND pa.scheduled_activity_id IS NULL
ORDER BY pa.created_at ASC LIMIT $3`, r.partners, rules.PartnerIntakeStatuses, intakeLimit)
	if err != nil {
		return nil, fmt.Errorf("todos: reading the partner's assignments: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id string
		var hasSchool, hasCluster bool
		var school, cluster *string
		var created *time.Time
		if err := row.Scan(&id, &hasSchool, &hasCluster, &school, &cluster, &created); err != nil {
			return todo{}, err
		}
		where := "Field work"
		switch {
		case hasSchool:
			where = pyStr(school)
		case hasCluster:
			where = pyStr(cluster)
		}
		age := 0
		if created != nil {
			age = int(r.today.Sub(localDate(*created)).Hours() / 24)
		}
		title := "Schedule or Return Assigned Activity"
		if hasSchool && !hasCluster {
			title = "Schedule or Return Assigned School"
		}
		priority := "medium"
		if age > intakeLateDays {
			priority = "high"
		}
		return todo{Title: title, Description: fmt.Sprintf("%s — assigned %d day(s) ago and awaiting your decision", where, age),
			Category: "Assignments", Priority: priority, StatusKey: "waiting_me", StatusLabel: "Waiting on Me",
			StatusTone: "info", DueLabel: "—", DueTone: "neutral", Actionable: true, Linked: where,
			ActionLabel: "Decide", ActionURL: "/partner/assignments/" + id, Shape: "/partner/assignments/{id}"}, nil
	})
}

// mfiTodos is the lending partners' section of
// _business_transformation_todos: loan records Salesforce returned, in the
// order they were returned. Its other rows (repayment data to update,
// portfolio errors, the monthly return) link to the Business Transformation
// page, which these roles may not open, so the queue drops them; should the
// page open to them, the reader is passed on.
func mfiTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if rules.OpenLinks[btPortfolioPage][r.role] {
		return nil, errPassOn
	}
	a := &btportfolio.Args{}
	where, err := btportfolio.LoansWhere(ctx, s.db, r.p, r.now, a)
	if err != nil {
		return nil, err
	}
	status := a.Add(rules.SalesforceReturnedStatus)
	limit := a.Add(mfiReturnedLimit)
	rows, err := s.db.Query(ctx, `SELECT s.name, COALESCE(l.external_loan_reference, '')
FROM bt_mfi_loan l JOIN school s ON s.id = l.school_id
WHERE `+where+` AND l.salesforce_status = `+status+`
ORDER BY l.salesforce_returned_at ASC NULLS LAST LIMIT `+limit, []any(*a)...)
	if err != nil {
		return nil, fmt.Errorf("todos: reading the returned loan records: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var school *string
		var reference string
		if err := row.Scan(&school, &reference); err != nil {
			return todo{}, err
		}
		// Description (the school and the return reason) is read only where
		// Linked is empty, which it never is here.
		return todo{Title: "Correct returned loan record", Category: "Business Transformation", Priority: "high",
			StatusKey: "returned", StatusLabel: "Returned", StatusTone: "danger", DueLabel: "Today", DueTone: "warning",
			Actionable: true, Linked: pyStr(school) + " · " + reference, ActionLabel: "Correct",
			ActionURL: "/loans#loan-record-title", Shape: "/loans#loan-record-title", Due: &r.today}, nil
	})
}
