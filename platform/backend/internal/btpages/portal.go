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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolcode"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// PortalPrefix is the MFI partner portal (mfi_portal_page over
// mfi_portal_context): /mfi-portal/<section>.
const PortalPrefix = "/mfi-portal/"

// portalPage is the page permission's door in the exported rules.
const portalPage = "/mfi-portal"

var portalTabs = [][2]string{{"dashboard", "Dashboard"}, {"loans", "Loans"}, {"monthly-return", "Monthly Portfolio Return"},
	{"data-issues", "Data Issues"}, {"reports", "Reports"}}

// portal is one section of the portal. A section the existing page does not
// know, or a reader who is not a lending partner's, is the existing page's
// own error and stays with it.
func (s *Service) portal(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !btportfolio.Opens(p.ActiveRole, portalPage) {
		return nil, true, pagegate.ErrNotAvailable
	}
	section := strings.TrimPrefix(path, PortalPrefix)
	if !btportfolio.MfiUser(p.ActiveRole) || !slices.Contains(btportfolio.Rules.Portal.Sections, section) {
		return nil, false, nil
	}
	now := s.now()
	f := btportfolio.ReadFilters(query, btportfolio.FilterKeys)
	fy, ok := fyOf(f, now)
	if !ok {
		return nil, false, nil
	}
	f["fy"] = fy
	links := []*screensv1.PageLink{}
	for _, t := range portalTabs {
		links = append(links, &screensv1.PageLink{Text: t[1], Href: PortalPrefix + t[0]})
	}
	blocks := []*screensv1.PageBlock{panel("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})}
	var body []*screensv1.PageBlock
	var err error
	switch section {
	case "dashboard", "reports":
		var m btportfolio.Metrics
		if m, err = btportfolio.PortfolioMetrics(ctx, s.db, p, fy, f, now); err == nil {
			l := btportfolio.Rules.MetricLabels
			body = []*screensv1.PageBlock{schoolprofile.Strip("Your MFI portfolio", []schoolprofile.StripFigure{
				{Label: l["bt_value_disbursed"], Value: ugx(m.ValueDisbursed), Helper: "Net confirmed in FY " + m.FY},
				{Label: l["bt_active_portfolio"], Value: ugx(m.Outstanding), Helper: "Ledger-derived outstanding principal"},
			})}
		}
	case "loans":
		body, err = s.portalLoans(ctx, p, f, now, query)
	case "monthly-return":
		body, err = s.portalReturns(ctx, p, query)
	default:
		body, err = s.portalIssues(ctx, p, query)
	}
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Uganda lending partner", Title: "MFI Partner Portal",
			Description: "A focused workspace for governed loan submissions, monthly portfolio returns and data corrections."},
		Blocks: append(blocks, body...), WebPath: path,
	}, true, nil
}

// portalLoans is "Your MFI loans". The School ID cell is a placeholder the
// web fills after the page is drawn (school_code); it is filled the same way
// here.
func (s *Service) portalLoans(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time, query url.Values) ([]*screensv1.PageBlock, error) {
	list, err := s.loanRows(ctx, p, f, now)
	if err != nil {
		return nil, err
	}
	head := panel("Your MFI loans", "Core identity locks after Salesforce confirmation; repayment updates remain open.",
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: "Create or update loan", Href: "/loans#loan-record-title"}}}}})
	columns := []string{"Reference", "School ID", "School", "Purpose", "Lifecycle", "Salesforce", "IA", "Action"}
	if len(list) == 0 {
		return []*screensv1.PageBlock{head, emptyTable(columns, "No loans submitted", "Use the governed loan entry workflow to submit the first record.")}, nil
	}
	r := btportfolio.Rules
	shown, pager := paged(list, "loans_page", query)
	refs := []string{}
	for _, x := range shown {
		refs = append(refs, x.schoolPK)
	}
	codes, err := schoolcode.Lookup(ctx, s.db, refs)
	if err != nil {
		return nil, err
	}
	out := []*screensv1.PageRow{}
	for _, x := range shown {
		school := &screensv1.PageCell{Text: closedschools.Collapse(x.school)}
		if x.school != "" && x.schoolPK != "" && slices.Contains(r.SchoolLinkRoles, p.ActiveRole) {
			school.Href = "/schools/" + url.PathEscape(x.schoolPK)
		}
		code := &screensv1.PageCell{Text: "—"}
		if x.schoolPK != "" {
			code.Text = codes.Of(x.schoolPK)
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(x.ref)}, code, school, {Text: closedschools.Collapse(x.purpose)},
			{Text: btportfolio.Label(r.LoanStatuses, x.status)}, {Text: btportfolio.Label(r.SalesforceStatuses, x.salesforce)},
			{Text: btportfolio.Label(r.IAStatuses, x.ia)}, {Text: "View"},
		}})
	}
	blocks := []*screensv1.PageBlock{head, table(columns, out)}
	if pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks, nil
}

// portalReturns is the Monthly Portfolio Return: the reader's partners'
// latest 24 submissions.
func (s *Service) portalReturns(ctx context.Context, p auth.Principal, query url.Values) ([]*screensv1.PageBlock, error) {
	ids, err := btportfolio.MfiIDs(ctx, s.db, p.UserID)
	if err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT x.reporting_month, COALESCE(m.name, ''), x.source_type, x.valid_rows, x.total_rows, x.exception_rows, x.status
FROM bt_portfolio_submission x LEFT JOIN bt_mfi_organization m ON m.id = x.mfi_id
WHERE x.mfi_id = ANY($1) ORDER BY x.reporting_month DESC LIMIT `+strconv.Itoa(btportfolio.Rules.Portal.SubmissionsShown), ids)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the monthly returns: %w", err)
	}
	type submission struct {
		month                  time.Time
		mfi, source, status    string
		valid, total, problems int
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (submission, error) {
		var x submission
		return x, r.Scan(&x.month, &x.mfi, &x.source, &x.valid, &x.total, &x.problems, &x.status)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the monthly returns: %w", err)
	}
	head := panel("Monthly Portfolio Return", "", text("API synchronization, secure bulk import and manual updates converge on the same period-based snapshots."))
	columns := []string{"Reporting month", "MFI", "Source", "Rows", "Exceptions", "Status"}
	if len(list) == 0 {
		return []*screensv1.PageBlock{head, emptyTable(columns, "No monthly returns", "The next open reporting month will appear here.")}, nil
	}
	r := btportfolio.Rules.Portal
	shown, pager := paged(list, "returns_page", query)
	out := []*screensv1.PageRow{}
	for _, x := range shown {
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: x.month.Format("January 2006")}, {Text: closedschools.Collapse(x.mfi)}, {Text: btportfolio.Label(r.SourceTypes, x.source)},
			{Text: fmt.Sprintf("%d / %d", x.valid, x.total)}, {Text: strconv.Itoa(x.problems)},
			badgeCell(btportfolio.Label(r.SubmissionStatuses, x.status), ""),
		}})
	}
	blocks := []*screensv1.PageBlock{head, table(columns, out)}
	if pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks, nil
}

// portalIssues is Data Issues: the reader's partners' first 100 open
// exceptions, oldest month and row first.
func (s *Service) portalIssues(ctx context.Context, p auth.Principal, query url.Values) ([]*screensv1.PageBlock, error) {
	ids, err := btportfolio.MfiIDs(ctx, s.db, p.UserID)
	if err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT x.reporting_month, COALESCE(e.row_number, 0), e.code, e.message
FROM bt_portfolio_data_exception e JOIN bt_portfolio_submission x ON x.id = e.submission_id
WHERE x.mfi_id = ANY($1) AND e.status = 'open' ORDER BY x.reporting_month, e.row_number LIMIT `+strconv.Itoa(btportfolio.Rules.Portal.IssuesShown), ids)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the data issues: %w", err)
	}
	type issue struct {
		month         time.Time
		row           int
		code, message string
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (issue, error) {
		var x issue
		return x, r.Scan(&x.month, &x.row, &x.code, &x.message)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the data issues: %w", err)
	}
	head := panel("Data Issues", "", text("Resolve row-level exceptions before MFI Admin certification."))
	columns := []string{"Month", "Row", "Issue", "Message"}
	if len(list) == 0 {
		return []*screensv1.PageBlock{head, emptyTable(columns, "No open data issues", "All submitted portfolio rows currently pass validation.")}, nil
	}
	shown, pager := paged(list, "issues_page", query)
	out := []*screensv1.PageRow{}
	for _, x := range shown {
		row := "—"
		if x.row != 0 {
			row = strconv.Itoa(x.row)
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: x.month.Format("Jan 2006")}, {Text: row}, {Text: closedschools.Collapse(x.code)}, {Text: closedschools.Collapse(x.message)},
		}})
	}
	blocks := []*screensv1.PageBlock{head, table(columns, out)}
	if pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks, nil
}
