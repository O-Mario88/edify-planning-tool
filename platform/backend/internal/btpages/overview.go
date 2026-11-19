// Package btpages is the Business Transformation pages as the existing
// application draws them (apps.business_transformation.frontend_views and
// pages/business_transformation/*.html) and the app's feed reads them, over
// the engine in internal/btportfolio. Acting on a case or a loan stays with
// the existing application.
package btpages

import (
	"context"
	"fmt"
	"math"
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

// OverviewPath is the BT workspace.
const OverviewPath = "/business-transformation/overview"

// WorkspacePath is the Business Transformation workspace
// (frontend_views.workspace_page), the same page as the overview under its
// own path.
const WorkspacePath = "/business-transformation"

// casesShown is workspace_context's cases[:50].
const casesShown = 50

// Service builds the BT pages from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the pages over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers the BT pages.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	switch path {
	case OverviewPath, WorkspacePath:
		return s.overview(ctx, p, path, query)
	case FinancePath, GovernmentPath:
		return s.portfolio(ctx, p, path, query)
	case LoansPath:
		return s.loans(ctx, p, query)
	case ImpactPath:
		return s.impact(ctx, p, query)
	}
	if strings.HasPrefix(path, PortalPrefix) {
		return s.portal(ctx, p, path, query)
	}
	return nil, false, nil
}

// fyOf is the filter's year or the operational one; ok is false for a year
// the existing page cannot read (int(fy) raises there).
func fyOf(f btportfolio.Filters, now time.Time) (string, bool) {
	fy := f["fy"]
	if fy == "" {
		return schooldirectory.OperationalFY(now), true
	}
	if _, err := strconv.Atoi(fy); err != nil {
		return "", false
	}
	return fy, true
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: closedschools.Collapse(t)}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

// nav is partials/business_transformation/workspace_nav.html: the BT
// officer's five tabs. Everyone else's lone Loans tab is not read.
func nav(role string) []*screensv1.PageBlock {
	if role != btportfolio.Rules.NavRole {
		return nil
	}
	links := []*screensv1.PageLink{{Text: "BT Overview", Href: OverviewPath}, {Text: "Loans", Href: "/loans"},
		{Text: "Business Accounting & Finance", Href: "/business-transformation/business-accounting-finance"},
		{Text: "Government Requirements", Href: "/business-transformation/government-requirements"},
		{Text: "Impact & Reports", Href: "/business-transformation/impact-reports"}}
	return []*screensv1.PageBlock{panel("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})}
}

// ugx is format_value for a MONEY_UGX figure: "UGX 68,500,000", whole
// shillings rounded half to even (the strip writes it short).
func ugx(m ledger.Money) string {
	shillings := math.RoundToEven(float64(m) / 100)
	return "UGX " + comma(int64(shillings))
}

func comma(n int64) string {
	s := strconv.FormatInt(n, 10)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		return "-" + s
	}
	return s
}

// ratio is MetricValue.ratio shown as a PERCENT figure: round(x, 1) written
// with :g, or "No data" over nothing.
func ratio(num, den float64) string {
	if den == 0 {
		return "No data"
	}
	v, _ := strconv.ParseFloat(strconv.FormatFloat(num/den*100, 'f', 1, 64), 64)
	return strconv.FormatFloat(v, 'g', -1, 64) + "%"
}

// scorecard is _portfolio_kpi_items' first four tiles.
func scorecard(m btportfolio.Metrics) *screensv1.PageBlock {
	l := btportfolio.Rules.MetricLabels
	return schoolprofile.Strip("Business Transformation scorecard", []schoolprofile.StripFigure{
		{Label: l["bt_value_disbursed"], Value: ugx(m.ValueDisbursed), Helper: "Net confirmed in FY " + m.FY},
		{Label: l["bt_schools_financed"], Value: comma(int64(m.SchoolsImpacted)), Helper: "Unique financed schools"},
		{Label: l["bt_active_portfolio"], Value: ugx(m.Outstanding), Helper: "Ledger-derived outstanding principal"},
		{Label: l["bt_par30"], Value: ratio(float64(m.PAR30), float64(m.Outstanding)), Helper: "Outstanding principal over 30 days past due"},
	})
}

func (s *Service) overview(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !btportfolio.Opens(p.ActiveRole, path) {
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
	filters, err := s.overviewFilters(ctx, p, f)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Uganda portfolio", Title: "Business Transformation",
		Description: "Move verified financial and compliance needs through readiness, responsible finance, loan-use verification, repayment monitoring, and impact."}
	blocks := append(nav(p.ActiveRole), filters, scorecard(metrics))
	if !btportfolio.SummaryOnly(p.ActiveRole) && !btportfolio.MfiUser(p.ActiveRole) {
		queue, err := s.triage(ctx, p, f, now, query)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, queue...)
	}
	blocks = append(blocks, panel("", "", text("Loading the scoped loan portfolio…")))
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}, true, nil
}

// overviewFilters is the filter bar the feed reads: the region and lending
// partner selects (the year is a text box, which it does not).
func (s *Service) overviewFilters(ctx context.Context, p auth.Principal, f btportfolio.Filters) (*screensv1.PageBlock, error) {
	regions := &screensv1.PageFilter{Name: "region", Label: "Region", Options: []*screensv1.PageFilterOption{{Label: "All regions"}}}
	rows, err := s.db.Query(ctx, `SELECT id, name FROM region ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the regions: %w", err)
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return nil, fmt.Errorf("btpages: reading the regions: %w", err)
		}
		regions.Options = append(regions.Options, &screensv1.PageFilterOption{Value: id, Label: name})
		if id == f["region"] {
			regions.Value = id
		}
	}
	rows.Close()
	partners, err := btportfolio.Partners(ctx, s.db, p)
	if err != nil {
		return nil, err
	}
	mfi := &screensv1.PageFilter{Name: "mfi", Label: "MFI", Options: []*screensv1.PageFilterOption{{Label: "All MFIs"}}}
	for _, x := range partners {
		mfi.Options = append(mfi.Options, &screensv1.PageFilterOption{Value: x.ID, Label: x.Name})
		if x.ID == f["mfi"] {
			mfi.Value = x.ID
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{regions, mfi}}}}, nil
}

// triage is the Triage queue card: the active-case count and the latest
// cases under the filters.
func (s *Service) triage(ctx context.Context, p auth.Principal, f btportfolio.Filters, now time.Time, query url.Values) ([]*screensv1.PageBlock, error) {
	a := &btportfolio.Args{}
	scoped, err := btportfolio.CasesWhere(ctx, s.db, p, now, a)
	if err != nil {
		return nil, err
	}
	var active int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM bt_case c WHERE `+scoped+` AND c.status IN ('recommended', 'triage', 'active', 'monitoring')`,
		*a...).Scan(&active); err != nil {
		return nil, fmt.Errorf("btpages: counting the active cases: %w", err)
	}
	where := scoped
	if f["case_status"] != "" {
		where += " AND c.status = " + a.Add(f["case_status"])
	}
	if f["region"] != "" {
		where += " AND s.region_id = " + a.Add(f["region"])
	}
	if f["district"] != "" {
		where += " AND s.district_id = " + a.Add(f["district"])
	}
	if q := f["q"]; q != "" {
		like := a.Add("%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(q) + "%")
		where += " AND (UPPER(s.name::text) LIKE UPPER(" + like + ") OR UPPER(s.school_id::text) LIKE UPPER(" + like + "))"
	}
	rows, err := s.db.Query(ctx, `SELECT c.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(d.name, ''), COALESCE(d.id, ''), COALESCE(g.name, ''),
  c.status, COALESCE(c.opened_fy, '')
FROM bt_case c INNER JOIN school s ON s.id = c.school_id LEFT JOIN district d ON d.id = s.district_id LEFT JOIN region g ON g.id = s.region_id
WHERE `+where+` ORDER BY c.created_at DESC LIMIT `+strconv.Itoa(casesShown), *a...)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the cases: %w", err)
	}
	type caseRow struct{ id, code, name, district, districtID, region, status, fy string }
	cases, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (caseRow, error) {
		var x caseRow
		return x, r.Scan(&x.id, &x.code, &x.name, &x.district, &x.districtID, &x.region, &x.status, &x.fy)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the cases: %w", err)
	}
	ids := []string{}
	for _, c := range cases {
		ids = append(ids, c.id)
	}
	recs := map[string][]string{}
	rows, err = s.db.Query(ctx, `SELECT case_id, kind FROM bt_case_recommendation WHERE case_id = ANY($1) ORDER BY created_at`, ids)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the recommendations: %w", err)
	}
	for rows.Next() {
		var id, kind string
		if err := rows.Scan(&id, &kind); err != nil {
			rows.Close()
			return nil, fmt.Errorf("btpages: reading the recommendations: %w", err)
		}
		recs[id] = append(recs[id], btportfolio.Label(btportfolio.Rules.RecommendationKinds, kind))
	}
	rows.Close()
	label := strconv.Itoa(active) + " active case"
	if active != 1 {
		label += "s"
	}
	blocks := []*screensv1.PageBlock{panel("Triage queue", "Verified need requiring an authorized human decision.", text(label))}
	t := &screensv1.PageTable{}
	for _, c := range []string{"School ID", "School", "Location", "Verified recommendation", "Status", "Opened", ""} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	number, pages := closedschools.PageOf(query.Get("cases_page"), len(cases), casesShown)
	for _, c := range cases[(number-1)*casesShown : min(number*casesShown, len(cases))] {
		district, region := c.district, c.region
		if district == "" {
			district = "District not set"
		}
		if region == "" {
			region = "Region not set"
		}
		rec := "No open recommendation"
		if r := recs[c.id]; len(r) > 0 {
			rec = strings.Join(r[:min(2, len(r))], " ")
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: c.code}, {Text: closedschools.Collapse(c.name), Href: "/schools/" + c.code},
			location(p.ActiveRole, district, c.districtID, region), {Text: closedschools.Collapse(rec)},
			{Text: btportfolio.Label(btportfolio.Rules.CaseStatuses, c.status), Tone: "primary", Badge: true},
			{Text: "FY " + c.fy}, {},
		}})
	}
	if len(cases) == 0 {
		t.EmptyMessage = "No Business Transformation cases match the current filters."
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No cases found No Business Transformation cases match the current filters."}}}}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("cases_page", number, pages, len(cases), casesShown, query, nil))
	}
	return blocks, nil
}

// location is the case's district (a link to its profile for a reader who
// may open one) and region.
func location(role, district, districtID, region string) *screensv1.PageCell {
	c := &screensv1.PageCell{Text: closedschools.Collapse(district + " · " + region)}
	if districtID != "" && slices.Contains(btportfolio.Rules.DistrictLinkRoles, role) {
		c.Href = "/districts/" + districtID
	}
	return c
}
