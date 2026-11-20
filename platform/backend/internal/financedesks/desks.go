package financedesks

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
)

// The seven desks that are one table each: what the view reads, as its
// template draws it.

// iaVerifiedIn is the accountability template's test `status in
// "ia_verified,closed,accountant_confirmed"`: Django's `in` on a string,
// which is a substring test.
const iaVerifiedIn = "ia_verified,closed,accountant_confirmed"

func ugxInt(n int64) string { return ugx(float64(n)) }

func (s *Service) accountability(ctx context.Context, _ role, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), r.staff_id, r.amount_disbursed, r.actual_spend, r.variance,
  COALESCE(r.netsuite_expense_id, ''), COALESCE(r.status, '')
FROM accountability_record r JOIN activity a ON a.id = r.activity_id
ORDER BY r.submitted_at DESC NULLS FIRST, r.id`)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the accountability records: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageRow, error) {
		var id, kind, actStatus, staff, netsuite, status string
		var disbursed, spend, variance int64
		if err := row.Scan(&id, &kind, &actStatus, &staff, &disbursed, &spend, &variance, &netsuite, &status); err != nil {
			return nil, err
		}
		ia := "Missing IA"
		if strings.Contains(iaVerifiedIn, actStatus) {
			ia = "Verified"
		}
		if netsuite == "" {
			netsuite = "NetSuite ID Required"
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(joined("#"+short(id), typeLabel(kind))), cell(staff), cell(ugxInt(disbursed)), cell(ugxInt(spend)),
			cell(ugxInt(variance)), cell(ia), cell(netsuite), badge(stafflogs.StatusLabel(status)),
			menu("View activity finance detail", detail(id)),
		}}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the accountability records: %w", err)
	}
	blocks := table(columns([]string{"Activity ID", "CCEO / Owner", "Amount Disbursed", "Actual Spend", "Variance",
		"IA Status", "NetSuite Expense ID", "Status", "Actions"}, "Actions"), list,
		"No active accountability records found in registry.", "accountability_records_page", query)
	blocks = append(blocks, netsuiteForm(local(s.now())))
	return page(header("Finance", "Accountability Pending Registry",
		"Audit and clear disbursement accountabilities. NetSuite Expense IDs are required for workflow closure."), blocks...), nil
}

// netsuiteForm is the accountability page's NetSuite drawer, as the feed
// reads its form: its entry date defaults to today.
func netsuiteForm(today time.Time) *screensv1.PageBlock {
	field := func(name, label, kind, value, placeholder string, required bool) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
			Name: name, Label: label, Kind: kind, Value: value, Placeholder: placeholder, Required: required}}}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Title: "Enter NetSuite Expense ID", SubmitLabel: "Save", Key: "netsuite-form",
		Items: []*screensv1.PageFormItem{
			field("netsuite_expense_id", "NetSuite Expense ID", "text", "", "e.g. EXP-2200115", true),
			field("amount_entered", "Amount Entered in NetSuite (UGX)", "number", "0", "", true),
			field("expense_date", "Expense Entry Date", "date", today.Format(time.DateOnly), "", true),
			field("notes", "Accountability Notes", "textarea", "", "Reconciled successfully...", false),
		},
	}}}
}

func (s *Service) advances(ctx context.Context, d role, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.responsible_staff_id, ''), COALESCE(a.school_id, ''), COALESCE(sc.name, ''), COALESCE(CASE WHEN sc.deleted_at IS NULL THEN sc.school_id END, ''), COALESCE(a.activity_type, ''),
  a.planned_date, COALESCE(a.est_cost_cents, 0)
FROM activity a LEFT JOIN school sc ON sc.id = a.school_id
WHERE a.deleted_at IS NULL AND a.delivery_type = 'staff'
  AND EXISTS (SELECT 1 FROM advance_request ar WHERE ar.activity_id = a.id AND ar.status = 'confirmed_for_advance')
  AND NOT (a.payment_status IS NOT NULL AND a.payment_status = ANY($1))
ORDER BY a.created_at DESC, a.id`, rules.PartnerPaidStatuses)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the advances: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageRow, error) {
		var id, staff, schoolID, name, filled, kind string
		var planned *time.Time
		var cost int64
		if err := row.Scan(&id, &staff, &schoolID, &name, &filled, &kind, &planned, &cost); err != nil {
			return nil, err
		}
		if staff == "" {
			staff = "Unassigned"
		}
		code, where := "—", cell("School / Cluster Cluster-wide")
		if schoolID != "" {
			code = closedschools.SchoolCode(filled)
			where = school(d, schoolID, "School / Cluster "+name)
		}
		day := ""
		if planned != nil {
			day = planned.Format("Jan 02, 2006")
		}
		amount := "—"
		if cost != 0 {
			amount = ugxInt(cost)
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell("Activity #" + short(id)), cell("Staff / CCEO " + staff), cell(code), where,
			cell(joined("Activity Type", typeLabel(kind))), cell(joined("Planned Date", day)),
			cell("Approved Amount " + amount), menu("View activity finance detail", detail(id)),
		}}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the advances: %w", err)
	}
	out := page(header("Finance", "Ready for Advance Disbursement",
		"Process approved fund requests ready for disbursement. These advances are released before execution."),
		table(columns([]string{"Activity / ID", "Staff / CCEO", "School ID", "School / Cluster", "Activity Type",
			"Planned Date", "Approved Amount", "Actions"}, "Actions"), list,
			"No approved advance requests ready for disbursement.", "advances_page", query)...)
	out.Dialogs = []*screensv1.PageDialog{{Key: "disburseOpen", Title: "Process Advance Disbursement", Blocks: []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Process Advance Disbursement",
			Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{}}}},
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: "Confirm Disbursement"}},
			{Kind: &screensv1.PagePanelItem_Text{Text: "Cancel"}},
		}}}},
	}}}
	return out, nil
}

func (s *Service) auditLog(ctx context.Context, _ role, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(l.activity_id, ''), a.id IS NOT NULL, l.event_type, l.actor_id, l.actor_role, COALESCE(l.new_value, ''), l.timestamp
FROM finance_audit_log l LEFT JOIN activity a ON a.id = l.activity_id
ORDER BY l.timestamp DESC NULLS FIRST, l.id`)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the audit log: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageRow, error) {
		var activityID, event, actor, actorRole, change string
		var linked bool
		var at *time.Time
		if err := row.Scan(&activityID, &linked, &event, &actor, &actorRole, &change, &at); err != nil {
			return nil, err
		}
		activity := cell("Unlinked")
		if linked {
			activity = &screensv1.PageCell{Text: "#" + short(activityID), Href: detail(activityID)}
		}
		stamp := ""
		if at != nil {
			stamp = local(*at).Format("Jan 02, 2006 15:04:05")
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			badge(strings.ToUpper(event)), activity, cell(joined(actor, actorRole)), cell(change), cell(stamp),
		}}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the audit log: %w", err)
	}
	return page(header("Finance", "Finance Audit Log Ledger",
		"Complete historic audit logs for all cash flows, payment methods, disbursements, reimbursements, and NetSuite reconciliations."),
		table(columns([]string{"Event Type", "Activity ID", "Actor Details", "Changes Recorded", "Timestamp"}, "Timestamp"),
			list, "No events found in finance audit log.", "logs_page", query)...), nil
}

// amendmentLimit is how many amendments the page lists.
const amendmentLimit = 100

// amendmentOpen is an amendment still to decide; Go draws only those (a
// decided one's reviewer line is the existing page's).
const amendmentOpen = "submitted"

func (s *Service) budgetAmendments(ctx context.Context, d role, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.activity_type, COALESCE(a.school_id, ''), COALESCE(sc.name, ''), COALESCE(CASE WHEN sc.deleted_at IS NULL THEN sc.school_id END, ''), m.original_date, m.new_date,
  m.original_fy, m.original_quarter, m.new_fy, m.new_quarter, m.original_amount, m.reason, m.status, COALESCE(m.review_note, '')
FROM budget_amendment m JOIN activity a ON a.id = m.activity_id LEFT JOIN school sc ON sc.id = a.school_id
ORDER BY m.created_at DESC, m.id LIMIT $1`, amendmentLimit)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the budget amendments: %w", err)
	}
	type amendment struct {
		kind, schoolID, name     *string
		filled                   string
		from, to                 *time.Time
		fromFY, fromQ, toFY, toQ *string
		amount                   int64
		reason, status, note     string
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (amendment, error) {
		var m amendment
		var schoolID, name string
		err := row.Scan(&m.kind, &schoolID, &name, &m.filled, &m.from, &m.to, &m.fromFY, &m.fromQ, &m.toFY, &m.toQ,
			&m.amount, &m.reason, &m.status, &m.note)
		m.schoolID, m.name = &schoolID, &name
		return m, err
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the budget amendments: %w", err)
	}
	h := header("", "Budget Amendments",
		"Sanctioned changes for finance-locked activities. Approving applies the move without touching the confirmed cost snapshot or its advances.")
	if len(list) == 0 {
		return page(h, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "No amendments", Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{
				{Kind: &screensv1.PagePanelItem_Text{Text: "When a staff member requests a date change on a locked activity, it appears here for review."}},
			}}}}), nil
	}
	var out []*screensv1.PageRow
	for _, m := range list {
		if m.status != amendmentOpen {
			return nil, errHandOn
		}
		code, where := "—", cell("—")
		if *m.schoolID != "" {
			code, where = closedschools.SchoolCode(m.filled), school(d, *m.schoolID, *m.name)
		}
		from := "—"
		if m.from != nil {
			from = m.from.Format("02 Jan 2006")
		}
		to := ""
		if m.to != nil {
			to = m.to.Format("02 Jan 2006")
		}
		move := from + " → " + to + " · " + pyStr(m.fromFY) + " " + pyStr(m.fromQ) + " → " + pyStr(m.toFY) + " " + pyStr(m.toQ)
		status := stafflogs.StatusLabel(m.status)
		if m.note != "" {
			status += " · " + m.note
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(pyStr(m.kind)), cell(code), where, cell(move), cell(strconv.FormatInt(m.amount, 10)), cell(m.reason),
			cell(status), {Actions: []*screensv1.PageAction{}},
		}})
	}
	return page(h, table(columns([]string{"Activity", "School ID", "School", "Move", "Amount (UGX)", "Reason", "Status",
		"Actions"}), out, "", "amendments_page", query)...), nil
}

// pyStr is str() of a value that may be None.
func pyStr(s *string) string {
	if s == nil {
		return "None"
	}
	return *s
}

func (s *Service) cleared(ctx context.Context, _ role, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.responsible_staff_id, ''), COALESCE(a.activity_type, ''), a.updated_at, cs.id IS NOT NULL,
  COALESCE(cs.final_budget_amount, 0), COALESCE(cs.disbursed_amount, 0), COALESCE(cs.actual_spend_amount, 0),
  COALESCE(cs.netsuite_expense_id, '')
FROM activity a LEFT JOIN completed_activity_snapshot cs ON cs.activity_id = a.id
WHERE a.deleted_at IS NULL AND a.status = 'closed'
ORDER BY a.updated_at DESC, a.id`)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the cleared ledger: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageRow, error) {
		var id, staff, kind, netsuite string
		var updated time.Time
		var snapshot bool
		var budget, disbursed, spend int64
		if err := row.Scan(&id, &staff, &kind, &updated, &snapshot, &budget, &disbursed, &spend, &netsuite); err != nil {
			return nil, err
		}
		if staff == "" {
			staff = "Unassigned"
		}
		money := func(n int64) string {
			if !snapshot {
				return "—"
			}
			return whole(float64(n)) + " UGX"
		}
		if netsuite == "" {
			netsuite = "—"
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell("#" + short(id)), cell(staff), badge(typeLabel(kind)), cell(money(budget)), cell(money(disbursed)),
			cell(money(spend)), cell(money(spend - disbursed)), cell(netsuite), cell(local(updated).Format("Jan 02, 2006")),
			button("Inspect", detail(id)),
		}}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the cleared ledger: %w", err)
	}
	return page(header("Finance", "Cleared / Closed Finance Ledger",
		"Archive of all financially closed activities. These records have passed program quality and financial accountability certifications."),
		table(columns([]string{"Activity ID", "Owner / Staff", "Activity Type", "Approved Amount", "Disbursed Amount",
			"Actual Spend", "Variance", "NetSuite ID", "Closed Date", "Actions"}, "Actions"), list,
			"No closed activities found in cleared ledger archive.", "cleared_closed_page", query)...), nil
}

func (s *Service) returned(ctx context.Context, d role, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.school_id, ''), COALESCE(sc.name, ''), COALESCE(CASE WHEN sc.deleted_at IS NULL THEN sc.school_id END, ''), ar.amount,
  COALESCE(ar.responsible_user_id, ''), u.id IS NOT NULL, u.name, COALESCE(ar.last_note, ''), ar.updated_at
FROM advance_request ar JOIN activity a ON a.id = ar.activity_id LEFT JOIN school sc ON sc.id = a.school_id
  LEFT JOIN "user" u ON u.id = ar.responsible_user_id
WHERE ar.status = 'returned'
ORDER BY ar.updated_at DESC, ar.id`)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the returned advances: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageRow, error) {
		var id, kind, schoolID, name, filled, owner, reason string
		var amount int64
		var known bool
		var ownerName *string
		var updated time.Time
		if err := row.Scan(&id, &kind, &schoolID, &name, &filled, &amount, &owner, &known, &ownerName, &reason, &updated); err != nil {
			return nil, err
		}
		to := "Unassigned"
		if known {
			to = pyStr(ownerName)
		}
		if reason == "" {
			reason = "No reason recorded."
		}
		code, where := "—", cell("Cluster-wide")
		if schoolID != "" {
			code, where = closedschools.SchoolCode(filled), school(d, schoolID, name)
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(joined("#"+short(id), typeLabel(kind))), cell(code), where, cell(budgetpage.UGXCompact(amount)), cell(to),
			cell(reason), cell(local(updated).Format("Jan 02, 2006 15:04")), badge("Awaiting Fix"), button("Inspect", detail(id)),
		}}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the returned advances: %w", err)
	}
	return page(header("Finance", "Returned Finance Ledger",
		"Track finance items returned to staff or partners for correction of receipts, amounts, or NetSuite details."),
		table(columns([]string{"Activity ID", "School ID", "School / Scope", "Amount", "Returned To", "Return Reason",
			"Returned Date", "Correction Status", "Actions"}, "Amount", "Actions"), list,
			"All corrections resolved. No returned finance items.", "returns_page", query)...), nil
}

func (s *Service) varianceReview(ctx context.Context, d role, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.school_id, ''), COALESCE(sc.name, ''), COALESCE(CASE WHEN sc.deleted_at IS NULL THEN sc.school_id END, ''), v.budgeted_amount,
  v.disbursed_amount, v.actual_spend, v.variance, COALESCE(v.reason, '')
FROM variance_review v JOIN activity a ON a.id = v.activity_id LEFT JOIN school sc ON sc.id = a.school_id
WHERE v.status = 'pending'
ORDER BY v.created_at, v.id`)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the variance reviews: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageRow, error) {
		var id, kind, schoolID, name, filled, reason string
		var budgeted, disbursed, spend, variance int64
		if err := row.Scan(&id, &kind, &schoolID, &name, &filled, &budgeted, &disbursed, &spend, &variance, &reason); err != nil {
			return nil, err
		}
		if reason == "" {
			reason = "No explanation provided."
		}
		code, where := "—", cell("Cluster-wide")
		if schoolID != "" {
			code, where = closedschools.SchoolCode(filled), school(d, schoolID, name)
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(joined("#"+short(id), typeLabel(kind))), cell(code), where, cell(ugxInt(budgeted)), cell(ugxInt(disbursed)),
			cell(ugxInt(spend)), cell(ugxInt(variance)), cell(reason), button("Reconcile", detail(id)),
		}}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the variance reviews: %w", err)
	}
	return page(header("Finance", "Variance Review Queue",
		"Review activities where the actual spend differs from the approved/disbursed amount. Verify reasons and approve variance adjustments."),
		table(columns([]string{"Activity ID", "School ID", "School / Scope", "Budgeted", "Disbursed", "Actual Spend",
			"Variance", "Reason", "Actions"}, "Actions"), list,
			"All variances resolved. No items pending review.", "reviews_page", query)...), nil
}
