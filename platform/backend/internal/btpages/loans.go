package btpages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// LoansPath is the Loans register (loan_page over loan_register_context).
const LoansPath = "/loans"

// loanFilterKeys is _loan_filters: the controls the register reads.
var loanFilterKeys = []string{"fy", "q", "mfi", "district", "status", "repayment_health",
	"salesforce_status", "application_status", "report_month", "page", "per_page"}

// tablePage is the paginate tag's TABLE_PAGE_SIZE.
const tablePage = 50

const (
	permLoanWrite      = "businessTransformation.loan.write"
	permRepaymentWrite = "businessTransformation.repayment.write"
	permConfirm        = "businessTransformation.salesforce.confirm"
	permExport         = "businessTransformation.export"
)

// loans is the register. A lending partner's own users get the loan and
// repayment forms, and a page with loan applications gets their follow-up
// forms; both stay with the existing page.
func (s *Service) loans(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !btportfolio.Opens(p.ActiveRole, LoansPath) {
		return nil, true, pagegate.ErrNotAvailable
	}
	canWrite, canExecute := btportfolio.Holds(p, permLoanWrite), btportfolio.Holds(p, permRepaymentWrite)
	if canWrite || canExecute || btportfolio.MfiUser(p.ActiveRole) {
		return nil, false, nil
	}
	now := s.now()
	raw := btportfolio.ReadFilters(query, loanFilterKeys)
	fy, ok := fyOf(raw, now)
	if !ok {
		return nil, false, nil
	}
	f := btportfolio.Filters{}
	for k, v := range raw {
		f[k] = v
	}
	f["fy"] = fy
	applications, err := s.applicationCount(ctx, p, f, now)
	if err != nil {
		return nil, true, err
	}
	if applications > 0 {
		return nil, false, nil
	}
	metrics, err := btportfolio.PortfolioMetrics(ctx, s.db, p, fy, f, now)
	if err != nil {
		return nil, true, err
	}
	filters, err := s.loanFilters(ctx, p, f)
	if err != nil {
		return nil, true, err
	}
	partners, err := s.lendingPartners(ctx, p, f, now, query)
	if err != nil {
		return nil, true, err
	}
	register, err := s.loanRegister(ctx, p, f, now, query)
	if err != nil {
		return nil, true, err
	}
	access := accessLabel(p, canWrite, canExecute)
	headItems := []*screensv1.PagePanelItem{text("Access follows your active platform role.")}
	if btportfolio.Holds(p, permExport) {
		href := "/loans/export.xlsx"
		if q := loanFilterQuery(raw); q != "" {
			href += "?" + q
		}
		headItems = append(headItems, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: "Export", Href: href}}}}})
	}
	if !btportfolio.Holds(p, permConfirm) {
		// The dotted badges (full access, Salesforce confirmation) are not read.
		headItems = append(headItems, text(access))
	}
	blocks := append(nav(p.ActiveRole), panel("", "", headItems...), filters, loanScorecard(metrics))
	blocks = append(blocks, applicationsBlocks(p)...)
	blocks = append(blocks, panel("Lending partner dashboard", "", text("All lending partners represented in the governed loan records matching the current filters.")))
	blocks = append(blocks, partners...)
	blocks = append(blocks, panel("Loan register", "Uganda school loans matching the current filters.", text(access)))
	blocks = append(blocks, register...)
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Uganda lending portfolio", Title: "Loans",
			Description: "Track every governed school loan across lending partners, Salesforce confirmation, disbursement, repayment position, and student reach."},
		Blocks: blocks, WebPath: LoansPath,
	}, true, nil
}

// accessLabel is loan_register_context's access_label.
func accessLabel(p auth.Principal, canWrite, canExecute bool) string {
	switch {
	case btportfolio.MfiUser(p.ActiveRole) && canWrite && canExecute:
		return "Full access · MFI scope"
	case btportfolio.Holds(p, permConfirm):
		return "Salesforce confirmation"
	case canWrite && canExecute:
		return "Full access"
	}
	return "Read only"
}

// loanFilterQuery is loan_page's filter_query: the set filters but the
// pager's, in the controls' order.
func loanFilterQuery(raw btportfolio.Filters) string {
	parts := []string{}
	for _, k := range loanFilterKeys {
		if v := raw[k]; v != "" && k != "page" && k != "per_page" {
			parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(v))
		}
	}
	return strings.Join(parts, "&")
}

// loanScorecard is _portfolio_kpi_items(operational=True): the value
// disbursed and the active portfolio.
func loanScorecard(m btportfolio.Metrics) *screensv1.PageBlock {
	l := btportfolio.Rules.MetricLabels
	return schoolprofile.Strip("Uganda loan scorecard", []schoolprofile.StripFigure{
		{Label: l["bt_value_disbursed"], Value: ugx(m.ValueDisbursed), Helper: "Net confirmed in FY " + m.FY},
		{Label: l["bt_active_portfolio"], Value: ugx(m.Outstanding), Helper: "Ledger-derived outstanding principal"},
	})
}

// applicationCount is how many applications scoped_applications lists under
// the application status and report month.
func (s *Service) applicationCount(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time) (int, error) {
	if !slices.Contains(btportfolio.Rules.Loans.ApplicationUpdateRoles, p.ActiveRole) && p.ActiveRole != "RegionalVicePresident" {
		return 0, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return 0, fmt.Errorf("btpages: resolving the reader's scope: %w", err)
	}
	args := []any{}
	where := "a.deleted_at IS NULL AND a.school_id IN (SELECT s.id FROM school s WHERE " + schooldirectory.AnalyticsReach(scope, &args) + ")"
	a := btportfolio.Args(args)
	if v := f["application_status"]; v != "" {
		where += " AND a.status = " + a.Add(v)
	}
	if m := f["report_month"]; len(m) == 7 && m[4] == '-' {
		if start, err := time.Parse(time.DateOnly, m+"-01"); err == nil {
			local := "(a.submitted_at AT TIME ZONE '" + btportfolio.Zone().String() + "')::date"
			where += " AND " + local + " >= " + a.Add(start.Format(time.DateOnly)) + "::date AND " + local + " < " +
				a.Add(start.AddDate(0, 1, 0).Format(time.DateOnly)) + "::date"
		}
	}
	var n int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM bt_loan_application a WHERE `+where, a...).Scan(&n); err != nil {
		return 0, fmt.Errorf("btpages: counting the loan applications: %w", err)
	}
	return n, nil
}

// applicationsBlocks is the School loan applications card with no
// applications to list (a page with some is passed on).
func applicationsBlocks(p auth.Principal) []*screensv1.PageBlock {
	head := panel("School loan applications", "Share the application link with interested schools, then keep each request moving until it becomes a processed loan.",
		text("Copy link"), &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: "Open form", Href: "/loan-applications/apply"}}}}})
	columns := []string{"School ID", "School", "Request", "Applicant", "Submitted", "Status", "Next follow-up"}
	if slices.Contains(btportfolio.Rules.Loans.ApplicationUpdateRoles, p.ActiveRole) {
		columns = append(columns, "Record follow-up")
	}
	return []*screensv1.PageBlock{head, emptyTable(columns, "No loan applications found", "Share the application link with an interested school or adjust the filters.")}
}

// emptyTable is a table whose only row is its empty state.
func emptyTable(columns []string, title, message string) *screensv1.PageBlock {
	t := table(columns, []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: title + " " + message}}}})
	t.GetTable().EmptyMessage = message
	return t
}

func table(columns []string, rows []*screensv1.PageRow) *screensv1.PageBlock {
	t := &screensv1.PageTable{Rows: rows}
	for _, c := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

// paged is the paginate tag over rows: the page's rows and its pager.
func paged[T any](rows []T, param string, query url.Values) ([]T, *screensv1.PageBlock) {
	number, pages := closedschools.PageOf(query.Get(param), len(rows), tablePage)
	shown := rows[min((number-1)*tablePage, len(rows)):min(number*tablePage, len(rows))]
	if pages <= 1 {
		return shown, nil
	}
	return shown, closedschools.PagerPanel(param, number, pages, len(rows), tablePage, query, nil)
}

// loanFilters is the register's filter bar as the feed reads it: the
// selects (the year and report month are inputs it does not read).
func (s *Service) loanFilters(ctx context.Context, p auth.Principal, f btportfolio.Filters) (*screensv1.PageBlock, error) {
	choice := func(name, label, all string, options [][2]string) *screensv1.PageFilter {
		x := &screensv1.PageFilter{Name: name, Label: label, Options: []*screensv1.PageFilterOption{{Label: all}}}
		for _, o := range options {
			x.Options = append(x.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
			if o[0] == f[name] {
				x.Value = o[0]
			}
		}
		return x
	}
	partners, err := btportfolio.Partners(ctx, s.db, p)
	if err != nil {
		return nil, err
	}
	mfis := [][2]string{}
	for _, x := range partners {
		mfis = append(mfis, [2]string{x.ID, x.Name})
	}
	rows, err := s.db.Query(ctx, `SELECT id, name FROM district ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the districts: %w", err)
	}
	districts, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
		var x [2]string
		return x, r.Scan(&x[0], &x[1])
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the districts: %w", err)
	}
	r := btportfolio.Rules
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
		choice("mfi", "Lending partner", "All lending partners", mfis),
		choice("district", "District", "All districts", districts),
		choice("status", "Loan status", "All statuses", r.LoanStatuses),
		choice("repayment_health", "Repayment health", "All repayment states", r.Loans.RepaymentStatuses),
		choice("salesforce_status", "Salesforce status", "All Salesforce states", r.SalesforceStatuses),
		choice("application_status", "Application status", "All application states", r.Loans.ApplicationStatuses),
	}}}}, nil
}

// scopedLoans is filter_loans(scoped_loans()) as a condition over
// btportfolio.LoanFrom.
func (s *Service) scopedLoans(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time) (string, *btportfolio.Args, error) {
	a := &btportfolio.Args{}
	where, err := btportfolio.LoansWhere(ctx, s.db, p, now, a)
	if err != nil {
		return "", nil, err
	}
	return where + btportfolio.FilterLoans(f, a), a, nil
}

type partnerRow struct {
	name, value                                  string
	loans, disbursed, schools, confirmed, atRisk int
	latest                                       *time.Time
}

// lendingPartners is lending_partner_dashboard and its table.
func (s *Service) lendingPartners(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time, query url.Values) ([]*screensv1.PageBlock, error) {
	where, a, err := s.scopedLoans(ctx, p, f, now)
	if err != nil {
		return nil, err
	}
	l := btportfolio.Rules.Loans
	disbursed, atRisk := a.Add(l.DisbursedStatuses), a.Add(l.AtRiskRepayment)
	rows, err := s.db.Query(ctx, `SELECT COALESCE(m.name, ''), count(l.id),
  count(l.id) FILTER (WHERE l.status = ANY(`+disbursed+`)),
  COALESCE(sum(l.disbursed_amount) FILTER (WHERE l.status = ANY(`+disbursed+`)), 0)::text,
  count(DISTINCT l.school_id) FILTER (WHERE l.status = ANY(`+disbursed+`)),
  count(l.id) FILTER (WHERE l.salesforce_status = 'confirmed'),
  count(l.id) FILTER (WHERE (SELECT r.status FROM bt_repayment_snapshot r WHERE r.loan_id = l.id ORDER BY r.as_of_date DESC, r.created_at DESC LIMIT 1) = ANY(`+atRisk+`)
    OR l.status = 'defaulted'),
  max(l.last_repayment_data_date)
FROM `+btportfolio.LoanFrom+` LEFT JOIN bt_mfi_organization m ON m.id = l.mfi_id
WHERE `+where+` GROUP BY l.mfi_id, m.name ORDER BY m.name`, *a...)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the lending partners: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (partnerRow, error) {
		var x partnerRow
		return x, r.Scan(&x.name, &x.loans, &x.disbursed, &x.value, &x.schools, &x.confirmed, &x.atRisk, &x.latest)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the lending partners: %w", err)
	}
	columns := []string{"Lending partner", "Loans", "Disbursed", "Value disbursed", "Schools impacted", "Salesforce confirmation", "At risk", "Latest repayment data"}
	if len(list) == 0 {
		return []*screensv1.PageBlock{emptyTable(columns, "No lending partners found", "No governed loans match the current filters.")}, nil
	}
	shown, pager := paged(list, "partners_page", query)
	out := []*screensv1.PageRow{}
	for _, x := range shown {
		row, err := partnerCells(x)
		if err != nil {
			return nil, err
		}
		out = append(out, row)
	}
	blocks := []*screensv1.PageBlock{table(columns, out)}
	if pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks, nil
}

// partnerCells is one lending partner row.
func partnerCells(x partnerRow) (*screensv1.PageRow, error) {
	value, err := ledger.ParseMoney(x.value)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading a lending partner's value disbursed: %w", err)
	}
	state := "Complete"
	if x.loans != x.confirmed {
		state = "Action required"
	}
	risk := &screensv1.PageCell{Text: "0"}
	if x.atRisk > 0 {
		risk = &screensv1.PageCell{Text: strconv.Itoa(x.atRisk), Tone: "primary", Badge: true}
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: closedschools.Collapse(x.name), Strong: x.name != ""}, {Text: strconv.Itoa(x.loans)}, {Text: strconv.Itoa(x.disbursed)},
		{Text: ugx(value)}, {Text: strconv.Itoa(x.schools)},
		{Text: fmt.Sprintf("%s %d of %d · %s%%", state, x.confirmed, x.loans, coverage(x.confirmed, x.loans))},
		risk, {Text: dmy(x.latest, "Not submitted")},
	}}, nil
}

// coverage is salesforce_coverage_pct through |default:"0": round(x, 1)
// written as Python writes a float ("50.0"), and "0" for none.
func coverage(confirmed, loans int) string {
	if loans == 0 || confirmed == 0 {
		return "0"
	}
	return strconv.FormatFloat(float64(confirmed)/float64(loans)*100, 'f', 1, 64)
}

type loanRow struct {
	ref, officer, code, school, district, region, mfi, purpose string
	edtech                                                     bool
	disbursed, approved, paid, outstanding                     *string
	status, health, salesforce, salesforceID, ia, impact       string
	lastData                                                   *time.Time
	updated                                                    time.Time
}

// loanRegister is the loan register table: the first 200 loans, the latest
// disbursement first (undisbursed loans lead, as Postgres sorts nulls).
func (s *Service) loanRegister(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time, query url.Values) ([]*screensv1.PageBlock, error) {
	where, a, err := s.scopedLoans(ctx, p, f, now)
	if err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT l.external_loan_reference, l.assigned_officer_reference, COALESCE(s.school_id, ''), COALESCE(s.name, ''),
  COALESCE(d.name, ''), COALESCE(g.name, ''), COALESCE(m.name, ''), COALESCE(p.label, ''), COALESCE(p.is_edtech, FALSE),
  l.disbursed_amount::text, l.approved_amount::text, r.amount_paid_during_period::text, r.outstanding_amount::text,
  l.status, COALESCE(r.status, ''), l.salesforce_status, COALESCE(l.salesforce_loan_id, ''), l.ia_validation_status, l.impact_status,
  l.last_repayment_data_date, l.updated_at
FROM `+btportfolio.LoanFrom+` LEFT JOIN bt_mfi_organization m ON m.id = l.mfi_id
  LEFT JOIN district d ON d.id = s.district_id LEFT JOIN region g ON g.id = s.region_id
  LEFT JOIN LATERAL (SELECT x.status, x.amount_paid_during_period, x.outstanding_amount FROM bt_repayment_snapshot x
    WHERE x.loan_id = l.id ORDER BY x.as_of_date DESC, x.created_at DESC LIMIT 1) r ON TRUE
WHERE `+where+` ORDER BY l.disbursement_date DESC, l.created_at DESC LIMIT `+strconv.Itoa(btportfolio.Rules.Loans.RowLimit), *a...)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the loan register: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (loanRow, error) {
		var x loanRow
		return x, r.Scan(&x.ref, &x.officer, &x.code, &x.school, &x.district, &x.region, &x.mfi, &x.purpose, &x.edtech,
			&x.disbursed, &x.approved, &x.paid, &x.outstanding, &x.status, &x.health, &x.salesforce, &x.salesforceID,
			&x.ia, &x.impact, &x.lastData, &x.updated)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the loan register: %w", err)
	}
	columns := []string{"Loan Reference", "School ID", "School", "MFI", "Purpose", "Amount", "Loan Status", "Repayment", "Salesforce", "IA", "Impact", "Last Updated", "Action"}
	if len(list) == 0 {
		return []*screensv1.PageBlock{emptyTable(columns, "No loans found", "No Uganda loans match the current filters.")}, nil
	}
	shown, pager := paged(list, "loans_page", query)
	canConfirm := btportfolio.Holds(p, permConfirm)
	out := []*screensv1.PageRow{}
	for _, x := range shown {
		cells, err := loanCells(x, canConfirm)
		if err != nil {
			return nil, err
		}
		out = append(out, &screensv1.PageRow{Cells: cells})
	}
	blocks := []*screensv1.PageBlock{table(columns, out)}
	if pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks, nil
}

// ugxOr is |ugx for an amount that may be missing.
func ugxOr(raw *string, none string) (string, error) {
	if raw == nil {
		return none, nil
	}
	m, err := ledger.ParseMoney(*raw)
	if err != nil {
		return "", fmt.Errorf("btpages: reading a loan amount: %w", err)
	}
	return ugx(m), nil
}

// badgeCell is a cell drawn as one pill, or the pill's words and the line
// under it (a pill ends in a line break, so a space parts them).
func badgeCell(label, after string) *screensv1.PageCell {
	if after == "" {
		return &screensv1.PageCell{Text: closedschools.Collapse(label), Tone: "primary", Badge: true}
	}
	return &screensv1.PageCell{Text: closedschools.Collapse(label + " " + after)}
}

// loanCells is one loan register row as the feed reads loans.html.
func loanCells(x loanRow, canConfirm bool) ([]*screensv1.PageCell, error) {
	r := btportfolio.Rules
	ref := x.ref
	if x.officer != "" {
		ref += "Officer " + x.officer
	}
	place := x.district
	if place == "" {
		place = "District not set"
	}
	if x.region != "" {
		place += " · " + x.region
	}
	purpose := x.purpose
	if x.edtech {
		purpose += " EdTech"
	}
	disbursed, err := ugxOr(x.disbursed, "Not disbursed")
	if err != nil {
		return nil, err
	}
	approved, err := ugxOr(x.approved, "—")
	if err != nil {
		return nil, err
	}
	repayment := badgeCell("Not Started", "")
	if x.health != "" {
		paid, err := ugxOr(x.paid, "—")
		if err != nil {
			return nil, err
		}
		outstanding, err := ugxOr(x.outstanding, "—")
		if err != nil {
			return nil, err
		}
		health := "Unknown"
		if slices.ContainsFunc(r.Loans.RepaymentStatuses, func(c [2]string) bool { return c[0] == x.health }) {
			health = btportfolio.Label(r.Loans.RepaymentStatuses, x.health)
		}
		repayment = badgeCell(health, "Paid "+paid+" · Outstanding "+outstanding)
	}
	salesforce := badgeCell("Pending", "")
	switch x.salesforce {
	case "confirmed":
		salesforce = badgeCell("Confirmed", x.salesforceID)
	case "returned":
		salesforce = badgeCell("Returned", "")
	}
	ia := "Pending"
	switch x.ia {
	case "verified":
		ia = "Verified"
	case "returned":
		ia = "Returned"
	}
	updated := dmy(x.lastData, "")
	if x.lastData == nil {
		local := x.updated.In(btportfolio.Zone())
		updated = dmy(&local, "")
	}
	action := "View"
	if canConfirm && x.salesforce == "pending" {
		action = "Complete"
	}
	return []*screensv1.PageCell{
		{Text: closedschools.Collapse(ref)}, {Text: x.code},
		{Text: closedschools.Collapse(x.school + place), Href: "/schools/" + x.code},
		{Text: closedschools.Collapse(x.mfi), Strong: x.mfi != ""}, {Text: closedschools.Collapse(purpose)},
		{Text: closedschools.Collapse(disbursed + "Approved " + approved)},
		badgeCell(btportfolio.Label(r.LoanStatuses, x.status), ""), repayment, salesforce,
		badgeCell(ia, ""), badgeCell(btportfolio.Label(r.ImpactStatuses, x.impact), ""),
		{Text: updated}, {Text: action},
	}, nil
}
