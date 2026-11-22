package prioritiesmaster

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/jackc/pgx/v5"
)

// StrategicPath is the Strategic Priorities configuration/overview page
// (apps.frontend.views.priority_views.priority_configuration_page).
const StrategicPath = "/strategic-priorities"

// strategicRoles are the authoritative roles allowed by can_open_url("/strategic-priorities").
var strategicRoles = map[string]bool{
	"Program Lead":          true,
	"CountryDirector":       true,
	"RegionalVicePresident": true,
	"RegionalProgramLead":   true,
	"ImpactAssessment":      true,
	"HumanResources":        true,
	"Admin":                 true,
}

func (s *Service) buildStrategic(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !strategicRoles[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	raw := strings.TrimSpace(query.Get("fy"))
	fy, err := s.year(ctx, raw)
	if err != nil {
		if errors.Is(err, errPassOn) {
			fy = schooldirectory.OperationalFY(s.now())
			raw = ""
		} else {
			return nil, true, err
		}
	}

	now := s.now()
	cycleStatus := "not_configured"
	var statusRaw string
	err = s.db.QueryRow(ctx, `
SELECT COALESCE(status, '') FROM hr_strategic_priority_cycle
WHERE financial_year = $1
ORDER BY status ASC LIMIT 1`, fy).Scan(&statusRaw)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, true, fmt.Errorf("prioritiesmaster: reading strategic cycle: %w", err)
	}
	if statusRaw != "" {
		cycleStatus = statusRaw
	}

	role := rules.Roles[p.ActiveRole]
	// Runners (CD, IA, Admin) see Uganda's country targets on /strategic-priorities
	// rather than being redirected away to /target-distribution.
	displayRole := role
	if role.Runner {
		displayRole = door{}
	}

	tabs := strategicTabs(p.ActiveRole, role)
	header := &screensv1.PageHeader{
		Eyebrow:     "Strategy",
		Title:       "Strategic Priorities",
		Description: fmt.Sprintf("Governed strategic priorities, milestones and targets for %s · FY %s.", country, fy),
		Badges: []*screensv1.PageBadge{{
			Text: cycleStatusLabel(cycleStatus),
			Tone: cycleStatusTone(cycleStatus),
		}},
	}

	blocks := []*screensv1.PageBlock{yearFilter(fy, schooldirectory.FYOptions(now))}
	if len(tabs) >= 2 {
		blocks = append(blocks, strategicRail(tabs, raw))
	}

	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	m, err := readMaster(ctx, s.db, p, displayRole, fy, today)
	if err != nil && !errors.Is(err, errPassOn) {
		return nil, true, err
	}

	priorityCount := 0
	milestoneCount := 0
	if m != nil {
		priorityCount = len(m.groups)
		milestoneCount = m.total
	} else if errors.Is(err, errPassOn) {
		// Priorities exist for this FY, but no milestones have been added yet.
		var emptyGroups []*priority
		emptyGroups, qerr := readStrategicPriorityTitles(ctx, s.db, fy)
		if qerr != nil {
			return nil, true, qerr
		}
		priorityCount = len(emptyGroups)
		blocks = append(blocks, strategicSummaryStrip(priorityCount, 0, cycleStatus))
		if len(emptyGroups) > 0 {
			blocks = append(blocks, prioritiesOnlyTable(emptyGroups))
		} else {
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
				Empty: fmt.Sprintf("No strategic priorities are configured for FY %s yet.", fy),
			}})
		}
		return &screensv1.GetPageResponse{Header: header, WebPath: StrategicPath, Blocks: blocks}, true, nil
	}

	blocks = append(blocks, strategicSummaryStrip(priorityCount, milestoneCount, cycleStatus))
	if m == nil {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: fmt.Sprintf("No strategic priorities are configured for FY %s yet.", fy),
		}})
	} else {
		blocks = append(blocks, m.blocks(displayRole)...)
	}

	return &screensv1.GetPageResponse{
		Header:  header,
		WebPath: StrategicPath,
		Blocks:  blocks,
	}, true, nil
}

func readStrategicPriorityTitles(ctx context.Context, db schooldirectory.Querier, fy string) ([]*priority, error) {
	rows, err := db.Query(ctx, `
SELECT id, title FROM hr_strategic_priority
WHERE fy = $1 AND level = 'country' AND country_id = $2
ORDER BY sequence`, fy, country)
	if err != nil {
		return nil, fmt.Errorf("prioritiesmaster: reading strategic priorities: %w", err)
	}
	defer rows.Close()
	var groups []*priority
	for rows.Next() {
		pr := &priority{}
		if err := rows.Scan(&pr.id, &pr.title); err != nil {
			return nil, fmt.Errorf("prioritiesmaster: scanning strategic priority: %w", err)
		}
		groups = append(groups, pr)
	}
	return groups, rows.Err()
}

func strategicTabs(activeRole string, role door) [][2]string {
	if len(role.Tabs) >= 2 {
		return role.Tabs
	}
	if activeRole == "CountryDirector" || activeRole == "ImpactAssessment" || activeRole == "Admin" {
		return [][2]string{
			{"Priority Setting", StrategicPath},
			{"Target Distribution", workspace},
		}
	}
	return [][2]string{
		{"Priority Setting", StrategicPath},
		{"Uganda Priorities", Path},
	}
}

func strategicRail(tabs [][2]string, raw string) *screensv1.PageBlock {
	links := &screensv1.PageLinkTabs{Scrolls: true}
	for _, t := range tabs {
		href := t[1]
		if raw != "" {
			href += "?" + url.Values{"fy": {raw}}.Encode()
		}
		links.Tabs = append(links.Tabs, &screensv1.PageLinkTab{
			Label:  t[0],
			Href:   href,
			Active: t[1] == StrategicPath,
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: links}}
}

func strategicSummaryStrip(priorities, milestones int, status string) *screensv1.PageBlock {
	return &screensv1.PageBlock{
		Kind: &screensv1.PageBlock_Strip{
			Strip: &screensv1.PageStrip{
				Title: "Cycle overview",
				Metrics: []*screensv1.PageMetric{
					{Label: "Priorities", Value: strconv.Itoa(priorities), Note: "Country strategic priorities"},
					{Label: "Milestones", Value: strconv.Itoa(milestones), Note: "Tracked FY milestones"},
					{Label: "Cycle status", Value: cycleStatusLabel(status), Note: "Governance state"},
				},
			},
		},
	}
}

func prioritiesOnlyTable(groups []*priority) *screensv1.PageBlock {
	t := &screensv1.PageTable{
		Columns: []*screensv1.PageColumn{
			{Label: "Priority"},
			{Label: "Milestones"},
		},
	}
	for _, g := range groups {
		t.Rows = append(t.Rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: g.title},
				{Text: "0 milestones configured"},
			},
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func cycleStatusLabel(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "active", "published":
		return "Active"
	case "locked", "approved":
		return "Locked"
	case "draft":
		return "Draft"
	case "archived":
		return "Archived"
	default:
		return "Not configured"
	}
}

func cycleStatusTone(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "active", "published", "locked", "approved":
		return "positive"
	case "draft":
		return "warning"
	default:
		return "plain"
	}
}
