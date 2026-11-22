package planningoversight

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// CountryPath is the Country Planning Oversight page.
const CountryPath = "/country-planning-oversight/"

func (s *Service) buildCountryOversight(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	fyOptions := schooldirectory.FYOptions(now)

	var totalSchools, coreSchools, ssaDone, fyActivities, openFollowUps int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM school WHERE deleted_at IS NULL AND operational_status = 'active'),
		(SELECT COUNT(*) FROM school WHERE deleted_at IS NULL AND operational_status = 'active' AND school_type = 'core'),
		(SELECT COUNT(*) FROM school WHERE deleted_at IS NULL AND operational_status = 'active' AND current_fy_ssa_status = 'done'),
		(SELECT COUNT(*) FROM activity WHERE deleted_at IS NULL AND fy = $1 AND status NOT IN ('cancelled', 'deferred')),
		(SELECT COUNT(*) FROM planning_oversight_follow_up WHERE status NOT IN ('resolved', 'closed', 'cancelled'))`,
		fy).Scan(&totalSchools, &coreSchools, &ssaDone, &fyActivities, &openFollowUps); err != nil {
		return nil, true, fmt.Errorf("planningoversight: country summary: %w", err)
	}

	rows, err := s.db.Query(ctx, `
SELECT COALESCE(r.name, 'Unassigned'),
       COUNT(DISTINCT s.id) AS schools,
       COUNT(DISTINCT s.id) FILTER (WHERE s.current_fy_ssa_status = 'done') AS ssa_done,
       COUNT(DISTINCT a.id) AS activities
FROM school s
LEFT JOIN region r ON r.id = s.region_id
LEFT JOIN activity a ON a.school_id = s.id AND a.deleted_at IS NULL AND a.fy = $1 AND a.status NOT IN ('cancelled', 'deferred')
WHERE s.deleted_at IS NULL AND s.operational_status = 'active'
GROUP BY r.name
ORDER BY schools DESC, r.name ASC
LIMIT 30`, fy)
	if err != nil {
		return nil, true, fmt.Errorf("planningoversight: region coverage: %w", err)
	}
	defer rows.Close()

	tbl := &screensv1.PageTable{
		Columns: []*screensv1.PageColumn{
			{Label: "Region"},
			{Label: "Active schools"},
			{Label: "SSA done (FY" + fy + ")"},
			{Label: "Planned & active work"},
		},
	}
	for rows.Next() {
		var regionName string
		var schools, done, acts int
		if err := rows.Scan(&regionName, &schools, &done, &acts); err != nil {
			return nil, true, fmt.Errorf("planningoversight: scanning region row: %w", err)
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: regionName},
				{Text: strconv.Itoa(schools)},
				{Text: strconv.Itoa(done)},
				{Text: strconv.Itoa(acts)},
			},
		})
	}
	if err := rows.Err(); err != nil {
		return nil, true, fmt.Errorf("planningoversight: region rows: %w", err)
	}

	filter := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: fy}
	for _, y := range fyOptions {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY" + y})
	}

	tabs := &screensv1.PageLinkTabs{
		Scrolls: true,
		Tabs: []*screensv1.PageLinkTab{
			{Label: "Country Oversight", Href: CountryPath, Active: true},
			{Label: "Team Oversight", Href: "/team-planning-oversight/"},
			{Label: "Coverage", Href: "/coverage"},
		},
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{filter}}}},
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
			Title: "Country planning overview · FY" + fy,
			Metrics: []*screensv1.PageMetric{
				{Label: "Active schools", Value: strconv.Itoa(totalSchools), Note: "Operating schools"},
				{Label: "Core schools", Value: strconv.Itoa(coreSchools), Note: "Core lifecycle"},
				{Label: "SSA verified", Value: strconv.Itoa(ssaDone), Note: "FY" + fy + " confirmed"},
				{Label: "Activities", Value: strconv.Itoa(fyActivities), Note: "Planned & delivered"},
				{Label: "Open follow-ups", Value: strconv.Itoa(openFollowUps), Note: "Oversight actions"},
			},
		}}},
	}
	if len(tbl.Rows) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "No regional planning coverage records found for FY" + fy + ".",
		}})
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: tbl}})
	}

	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Oversight",
			Title:       "Country Planning Oversight",
			Description: "Regional planning coverage, SSA progress, and follow-ups across Uganda · FY " + fy + ".",
		},
		WebPath: CountryPath,
		Blocks:  blocks,
	}, true, nil
}
