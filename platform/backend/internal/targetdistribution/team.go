package targetdistribution

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

// TeamPath is the Programme Lead "My Team" target distribution workspace.
const TeamPath = "/target-distribution/team"

var teamDistRoles = map[string]bool{
	"Program Lead":     true,
	"ImpactAssessment": true,
	"Admin":            true,
}

func (s *Service) buildTeam(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !teamDistRoles[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}

	var sql string
	var args []any
	if p.ActiveRole == "Program Lead" && p.StaffProfileID != "" {
		sql = `
SELECT a.id, COALESCE(m.title, 'Milestone'), COALESCE(a.allocated_target::text, '0'),
       COALESCE(m.target_unit, ''), COALESCE(a.status, ''),
       (SELECT COUNT(*) FROM hr_milestone_allocation c WHERE c.parent_id = a.id AND c.status IN ('draft', 'approved'))
FROM hr_milestone_allocation a
JOIN hr_priority_milestone m ON m.id = a.milestone_id
JOIN hr_strategic_priority sp ON sp.id = m.priority_id
WHERE sp.fy = $1 AND a.allocated_to_type = 'team' AND a.team_id = $2 AND a.status IN ('draft', 'approved')
ORDER BY sp.sequence ASC, m.source_order ASC
LIMIT 60`
		args = []any{fy, p.StaffProfileID}
	} else {
		sql = `
SELECT a.id, COALESCE(m.title, 'Milestone'), COALESCE(a.allocated_target::text, '0'),
       COALESCE(m.target_unit, ''), COALESCE(a.status, ''),
       (SELECT COUNT(*) FROM hr_milestone_allocation c WHERE c.parent_id = a.id AND c.status IN ('draft', 'approved'))
FROM hr_milestone_allocation a
JOIN hr_priority_milestone m ON m.id = a.milestone_id
JOIN hr_strategic_priority sp ON sp.id = m.priority_id
WHERE sp.fy = $1 AND a.allocated_to_type = 'team' AND a.status IN ('draft', 'approved')
ORDER BY sp.sequence ASC, m.source_order ASC
LIMIT 60`
		args = []any{fy}
	}

	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, true, fmt.Errorf("targetdistribution: reading team allocations: %w", err)
	}
	defer rows.Close()

	tbl := &screensv1.PageTable{
		Columns: []*screensv1.PageColumn{
			{Label: "Milestone"},
			{Label: "Team target"},
			{Label: "Status"},
			{Label: "Officer allocations"},
		},
	}
	var distributed, pending int
	for rows.Next() {
		var id, title, target, unit, status string
		var childCount int
		if err := rows.Scan(&id, &title, &target, &unit, &status, &childCount); err != nil {
			return nil, true, fmt.Errorf("targetdistribution: scanning team allocation: %w", err)
		}
		if childCount > 0 {
			distributed++
		} else {
			pending++
		}
		display := strings.TrimSpace(target + " " + unit)
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: title},
				{Text: display},
				{Text: status},
				{Text: strconv.Itoa(childCount) + " officer(s)"},
			},
		})
	}
	if err := rows.Err(); err != nil {
		return nil, true, fmt.Errorf("targetdistribution: team allocation rows: %w", err)
	}

	filter := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: fy}
	for _, y := range schooldirectory.FYOptions(now) {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY" + y})
	}

	tabs := &screensv1.PageLinkTabs{
		Scrolls: true,
		Tabs: []*screensv1.PageLinkTab{
			{Label: "Priority Setting", Href: "/strategic-priorities"},
			{Label: "Target Distribution", Href: "/priorities/master"},
			{Label: "My Team", Href: TeamPath, Active: true},
			{Label: "Team Guidance", Href: "/priorities/guidance"},
		},
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{filter}}}},
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
			Title: "My Team target distribution · FY" + fy,
			Metrics: []*screensv1.PageMetric{
				{Label: "Team targets", Value: strconv.Itoa(len(tbl.Rows)), Note: "Received from IA"},
				{Label: "Distributed", Value: strconv.Itoa(distributed), Note: "Split across officers"},
				{Label: "Awaiting split", Value: strconv.Itoa(pending), Note: "Not yet distributed"},
			},
		}}},
	}
	if len(tbl.Rows) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "No team milestone allocations are assigned for FY" + fy + " yet.",
		}})
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: tbl}})
	}

	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Strategy",
			Title:       "My Team Targets",
			Description: "Milestone targets assigned to your team and distributed across officers · FY " + fy + ".",
		},
		WebPath: TeamPath,
		Blocks:  blocks,
	}, true, nil
}
