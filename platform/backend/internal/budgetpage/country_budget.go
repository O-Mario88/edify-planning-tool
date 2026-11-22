package budgetpage

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// CountryBudgetPath is the Monthly General Budget page (/country-budget).
const CountryBudgetPath = "/country-budget"

var countryBudgetRoles = map[string]bool{
	"CountryDirector":       true,
	"RegionalVicePresident": true,
	"ImpactAssessment":      true,
	"Accountant":            true,
	"Admin":                 true,
}

func (s *Service) countryBudget(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !countryBudgetRoles[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}

	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(month_key, ''), COALESCE(country_id, 'Uganda'), COALESCE(status, ''),
       COALESCE(total_amount, 0), COALESCE(activity_count, 0), COALESCE(submission_version, 1)
FROM monthly_work_plan_budget
WHERE fy = $1
ORDER BY month_key DESC
LIMIT 24`, fy)
	if err != nil {
		return nil, true, fmt.Errorf("budgetpage: reading monthly general budgets: %w", err)
	}
	defer rows.Close()

	tbl := &screensv1.PageTable{
		Columns: []*screensv1.PageColumn{
			{Label: "Month"},
			{Label: "Country"},
			{Label: "Status"},
			{Label: "Activities"},
			{Label: "Total (UGX)"},
			{Label: "Version"},
		},
	}
	var totalUGX int64
	var pendingCount, approvedCount int
	for rows.Next() {
		var id, monthKey, countryID, status string
		var amount int64
		var actCount, version int
		if err := rows.Scan(&id, &monthKey, &countryID, &status, &amount, &actCount, &version); err != nil {
			return nil, true, fmt.Errorf("budgetpage: scanning monthly budget: %w", err)
		}
		totalUGX += amount
		switch status {
		case "approved":
			approvedCount++
		case "submitted_to_rvp", "under_cd_review", "returned_by_rvp":
			pendingCount++
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: monthKey},
				{Text: countryID},
				{Text: status},
				{Text: strconv.Itoa(actCount)},
				{Text: formatUGX(amount)},
				{Text: "v" + strconv.Itoa(version)},
			},
		})
	}
	if err := rows.Err(); err != nil {
		return nil, true, fmt.Errorf("budgetpage: iterating monthly budgets: %w", err)
	}

	var annualCount int
	_ = s.db.QueryRow(ctx, `SELECT COUNT(*) FROM country_annual_budget WHERE fy = $1`, fy).Scan(&annualCount)

	filter := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: fy}
	for _, y := range schooldirectory.FYOptions(now) {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY" + y})
	}

	tabs := &screensv1.PageLinkTabs{
		Scrolls: true,
		Tabs: []*screensv1.PageLinkTab{
			{Label: "General Budget", Href: CountryBudgetPath, Active: true},
			{Label: "Fund Allocation", Href: FundAllocationPath},
			{Label: "Disbursements", Href: "/disbursements"},
		},
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{filter}}}},
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
			Title: "Country General Budget · FY" + fy,
			Metrics: []*screensv1.PageMetric{
				{Label: "Monthly budgets", Value: strconv.Itoa(len(tbl.Rows)), Note: "FY" + fy + " periods"},
				{Label: "Awaiting action", Value: strconv.Itoa(pendingCount), Note: "Submitted or returned"},
				{Label: "Approved", Value: strconv.Itoa(approvedCount), Note: "Ready for disbursement"},
				{Label: "Annual baselines", Value: strconv.Itoa(annualCount), Note: "Country FY baseline"},
				{Label: "Total budgeted", Value: "UGX " + formatUGX(totalUGX), Note: "Across listed months"},
			},
		}}},
	}
	if len(tbl.Rows) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "No monthly General Budgets have been compiled for FY" + fy + " yet.",
		}})
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: tbl}})
	}

	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Finance & Budget",
			Title:       "Country General Budget",
			Description: "Monthly work plan budgets and CD/RVP approval workflow · FY " + fy + ".",
		},
		WebPath: CountryBudgetPath,
		Blocks:  blocks,
	}, true, nil
}

func formatUGX(n int64) string {
	neg := n < 0
	if neg {
		n = -n
	}
	s := strconv.FormatInt(n, 10)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		return "-" + s
	}
	return s
}
