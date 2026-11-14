package btpages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// ImpactPath is Impact & Reports (impact_reports_page over
// impact_reports_context).
const ImpactPath = "/business-transformation/impact-reports"

// cohortsShown is impact_reports_context's cohorts[:50].
const cohortsShown = 50

func (s *Service) impact(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !btportfolio.Opens(p.ActiveRole, ImpactPath) {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	f := btportfolio.ReadFilters(query, btportfolio.FilterKeys)
	fy, ok := fyOf(f, now)
	if !ok {
		return nil, false, nil
	}
	f["fy"] = fy
	metrics, err := btportfolio.PortfolioMetrics(ctx, s.db, p, fy, f, now)
	if err != nil {
		return nil, true, err
	}
	pipeline, err := s.impactPipeline(ctx, p, f, now, query)
	if err != nil {
		return nil, true, err
	}
	cohorts, err := s.cohorts(ctx, p, f, now, query)
	if err != nil {
		return nil, true, err
	}
	status := &screensv1.PageFilter{Name: "impact_status", Label: "Impact status", Options: []*screensv1.PageFilterOption{{Label: "All impact states"}}}
	for _, o := range btportfolio.Rules.ImpactStatuses {
		status.Options = append(status.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if o[0] == f["impact_status"] {
			status.Value = o[0]
		}
	}
	blocks := append(nav(p.ActiveRole),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{status}}}},
		schoolprofile.Strip("Impact headline", []schoolprofile.StripFigure{
			{Label: "Schools financed", Value: strconv.Itoa(metrics.SchoolsImpacted), Helper: "Unique schools"},
			{Label: "Students reached", Value: strconv.Itoa(metrics.StudentsReached), Helper: "Current enrolment, counted once per school"},
			{Label: "Loan use verified", Value: strconv.Itoa(metrics.VerificationDone), Helper: "IA-verified assessments"},
			{Label: "Positive impact", Value: strconv.Itoa(metrics.PositiveImpact), Helper: "IA-published positive classifications"},
		}),
		panel("Loan impact pipeline", "", text("BT prepares each due conclusion from verified evidence; someone other than the preparer verifies it before publication. No figure here claims the loan caused a change.")))
	blocks = append(blocks, pipeline...)
	blocks = append(blocks, panel("Disbursement cohort analysis", "", text("Recent loans are not compared unfairly with mature investments.")))
	blocks = append(blocks, cohorts...)
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Uganda Business Transformation", Title: "Impact & Reports",
			Description: "Loan use, loan impact conclusions and disbursement cohorts. Business Transformation prepares each conclusion from verified evidence; someone else verifies it before it is published."},
		Blocks: blocks, WebPath: ImpactPath,
	}, true, nil
}

type assessmentRow struct {
	id, schoolPK, code, school, mfi, purpose, classification, ia string
	due                                                          time.Time
}

// impactPipeline is the Loan impact pipeline table: the first 200
// assessments of the filtered loans, soonest due first. The BT officer, who
// prepares conclusions, gets Prepare on each unverified one that is due.
func (s *Service) impactPipeline(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time, query url.Values) ([]*screensv1.PageBlock, error) {
	where, a, err := s.scopedLoans(ctx, p, f, now)
	if err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT i.id, COALESCE(s.id, ''), COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(m.name, ''), COALESCE(p.label, ''),
  i.classification, i.ia_status, i.due_date
FROM bt_loan_impact_assessment i JOIN (SELECT l.* FROM `+btportfolio.LoanFrom+` WHERE `+where+`) l ON l.id = i.loan_id
  LEFT JOIN school s ON s.id = l.school_id LEFT JOIN bt_mfi_organization m ON m.id = l.mfi_id LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id
ORDER BY i.due_date, i.id LIMIT `+strconv.Itoa(btportfolio.Rules.Loans.RowLimit), *a...)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the impact assessments: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (assessmentRow, error) {
		var x assessmentRow
		return x, r.Scan(&x.id, &x.schoolPK, &x.code, &x.school, &x.mfi, &x.purpose, &x.classification, &x.ia, &x.due)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the impact assessments: %w", err)
	}
	preparer := p.ActiveRole == btportfolio.Rules.NavRole
	columns := []string{"School ID", "School", "MFI / Purpose", "Due", "Classification", "IA"}
	if preparer {
		columns = append(columns, "")
	}
	if len(list) == 0 {
		return []*screensv1.PageBlock{emptyTable(columns, "No impact assessments", "Assessments will be scheduled from disbursement cohorts.")}, nil
	}
	today := now.In(btportfolio.Zone()).Format(time.DateOnly)
	shown, pager := paged(list, "impact_page", query)
	out := []*screensv1.PageRow{}
	for _, x := range shown {
		school := &screensv1.PageCell{Text: closedschools.Collapse(x.school)}
		if x.school != "" && x.schoolPK != "" && slices.Contains(btportfolio.Rules.SchoolLinkRoles, p.ActiveRole) {
			school.Href = "/schools/" + url.PathEscape(x.schoolPK)
		}
		cells := []*screensv1.PageCell{{Text: x.code}, school, {Text: closedschools.Collapse(x.mfi + x.purpose)},
			{Text: x.due.Format("02 Jan 2006")},
			badgeCell(btportfolio.Label(btportfolio.Rules.ImpactStatuses, x.classification), ""),
			badgeCell(btportfolio.Label(btportfolio.Rules.IAStatuses, x.ia), "")}
		if preparer {
			action := &screensv1.PageCell{}
			if x.ia != "verified" && x.due.Format(time.DateOnly) <= today {
				action.Actions = []*screensv1.PageAction{{Key: "button", Label: "Prepare", Primary: true, Enabled: true,
					Href: "/ia/lending-evidence/conclusions/" + x.id + "/", Drawer: true}}
			}
			cells = append(cells, action)
		}
		out = append(out, &screensv1.PageRow{Cells: cells})
	}
	blocks := []*screensv1.PageBlock{table(columns, out)}
	if pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks, nil
}

// cohorts is the Disbursement cohort analysis: disbursed loans by year and
// purpose, the latest year first.
func (s *Service) cohorts(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time, query url.Values) ([]*screensv1.PageBlock, error) {
	where, a, err := s.scopedLoans(ctx, p, f, now)
	if err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT EXTRACT(YEAR FROM l.disbursement_date)::int, COALESCE(p.label, ''), count(l.id), count(DISTINCT l.school_id)
FROM `+btportfolio.LoanFrom+` WHERE `+where+` AND l.disbursement_date IS NOT NULL
GROUP BY 1, p.label ORDER BY 1 DESC, p.label LIMIT `+strconv.Itoa(cohortsShown), *a...)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the disbursement cohorts: %w", err)
	}
	type cohort struct {
		year           int
		purpose        string
		loans, schools int
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (cohort, error) {
		var x cohort
		return x, r.Scan(&x.year, &x.purpose, &x.loans, &x.schools)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the disbursement cohorts: %w", err)
	}
	columns := []string{"Cohort", "Purpose", "Loans", "Schools"}
	if len(list) == 0 {
		return []*screensv1.PageBlock{emptyTable(columns, "No cohorts yet", "Disbursed loans will appear here by year and purpose.")}, nil
	}
	shown, pager := paged(list, "cohorts_page", query)
	out := []*screensv1.PageRow{}
	for _, x := range shown {
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: strconv.Itoa(x.year)}, {Text: closedschools.Collapse(x.purpose)},
			{Text: strconv.Itoa(x.loans)}, {Text: strconv.Itoa(x.schools)}}})
	}
	blocks := []*screensv1.PageBlock{table(columns, out)}
	if pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks, nil
}
