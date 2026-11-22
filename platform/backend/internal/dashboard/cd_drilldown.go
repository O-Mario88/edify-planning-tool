package dashboard

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

// CDDrilldownPath is the Country Director analytics drilldown page.
const CDDrilldownPath = "/analytics/country-director/drilldown"

var cdDrilldownRoles = map[string]bool{
	"CountryDirector":  true,
	"ImpactAssessment": true,
	"Admin":            true,
}

func (s *Service) buildCDDrilldown(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !cdDrilldownRoles[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	drill := strings.TrimSpace(query.Get("drill"))
	if drill == "" {
		drill = "risk"
	}

	var title, subtitle string
	var tbl *screensv1.PageTable

	switch drill {
	case "district_low_lship":
		title = "District SSA Performance"
		subtitle = "Districts ordered by lowest confirmed SSA average · FY " + fy + "."
		rows, err := s.db.Query(ctx, `
SELECT COALESCE(d.name, 'Unassigned'), COUNT(DISTINCT s.id), ROUND(AVG(sr.average_score)::numeric, 1)::text
FROM school s
LEFT JOIN district d ON d.id = s.district_id
JOIN ssa_record sr ON sr.school_id = s.id AND sr.deleted_at IS NULL AND sr.verification_status = 'confirmed' AND sr.average_score IS NOT NULL
WHERE s.deleted_at IS NULL AND s.operational_status = 'active'
GROUP BY d.name
ORDER BY AVG(sr.average_score) ASC
LIMIT 30`)
		if err != nil {
			return nil, true, fmt.Errorf("dashboard: cd drilldown district: %w", err)
		}
		defer rows.Close()
		tbl = &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "District"}, {Label: "Assessed schools"}, {Label: "Avg SSA"}}}
		for rows.Next() {
			var name, avg string
			var cnt int
			if err := rows.Scan(&name, &cnt, &avg); err != nil {
				return nil, true, err
			}
			tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: name}, {Text: strconv.Itoa(cnt)}, {Text: avg}}})
		}
	case "partner":
		title = "Partner Delivery Oversight"
		subtitle = "Active partners and FY " + fy + " delivery volume."
		rows, err := s.db.Query(ctx, `
SELECT p.name, COUNT(a.id) AS total, COUNT(a.id) FILTER (WHERE a.status = 'verified') AS verified
FROM partner p
LEFT JOIN activity a ON a.assigned_partner_id = p.id AND a.deleted_at IS NULL AND a.fy = $1
WHERE p.deleted_at IS NULL
GROUP BY p.id, p.name
ORDER BY total DESC, p.name ASC
LIMIT 30`, fy)
		if err != nil {
			return nil, true, fmt.Errorf("dashboard: cd drilldown partner: %w", err)
		}
		defer rows.Close()
		tbl = &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Partner"}, {Label: "FY activities"}, {Label: "Verified"}}}
		for rows.Next() {
			var name string
			var total, verified int
			if err := rows.Scan(&name, &total, &verified); err != nil {
				return nil, true, err
			}
			tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: name}, {Text: strconv.Itoa(total)}, {Text: strconv.Itoa(verified)}}})
		}
	case "pl":
		title = "Programme Lead Oversight"
		subtitle = "Supervised teams and FY " + fy + " activity delivery."
		rows, err := s.db.Query(ctx, `
SELECT COALESCE(u.name, 'Programme Lead'), COUNT(DISTINCT ssa.supervisee_id) AS officers
FROM staff_profile sp
JOIN "user" u ON u.id = sp.user_id
LEFT JOIN staff_supervisor_assignment ssa ON ssa.supervisor_id = sp.id
WHERE sp.deleted_at IS NULL AND u.active_role = 'Program Lead' AND u.deleted_at IS NULL
GROUP BY sp.id, u.name
ORDER BY u.name ASC
LIMIT 30`)
		if err != nil {
			return nil, true, fmt.Errorf("dashboard: cd drilldown pl: %w", err)
		}
		defer rows.Close()
		tbl = &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Programme Lead"}, {Label: "Supervised officers"}}}
		for rows.Next() {
			var name string
			var officers int
			if err := rows.Scan(&name, &officers); err != nil {
				return nil, true, err
			}
			tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: name}, {Text: strconv.Itoa(officers)}}})
		}
	case "budget":
		title = "Country Budget Utilization"
		subtitle = "Monthly work plan budgets for FY " + fy + "."
		rows, err := s.db.Query(ctx, `
SELECT COALESCE(month_key, ''), COALESCE(status, ''), COALESCE(activity_count, 0), COALESCE(total_amount, 0)
FROM monthly_work_plan_budget
WHERE fy = $1
ORDER BY month_key DESC
LIMIT 24`, fy)
		if err != nil {
			return nil, true, fmt.Errorf("dashboard: cd drilldown budget: %w", err)
		}
		defer rows.Close()
		tbl = &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Month"}, {Label: "Status"}, {Label: "Activities"}, {Label: "Total (UGX)"}}}
		for rows.Next() {
			var monthKey, status string
			var acts int
			var total int64
			if err := rows.Scan(&monthKey, &status, &acts, &total); err != nil {
				return nil, true, err
			}
			tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: monthKey}, {Text: status}, {Text: strconv.Itoa(acts)}, {Text: strconv.FormatInt(total, 10)}}})
		}
	default:
		title = "Schools Missing Verified SSA"
		subtitle = "Active operating schools without confirmed SSA in FY " + fy + "."
		rows, err := s.db.Query(ctx, `
SELECT s.name, COALESCE(d.name, 'Unassigned'), COALESCE(s.school_type, '')
FROM school s
LEFT JOIN district d ON d.id = s.district_id
WHERE s.deleted_at IS NULL AND s.operational_status = 'active' AND COALESCE(s.current_fy_ssa_status, '') <> 'done'
ORDER BY d.name ASC NULLS LAST, s.name ASC
LIMIT 50`)
		if err != nil {
			return nil, true, fmt.Errorf("dashboard: cd drilldown risk: %w", err)
		}
		defer rows.Close()
		tbl = &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "School"}, {Label: "District"}, {Label: "School type"}}}
		for rows.Next() {
			var name, district, stype string
			if err := rows.Scan(&name, &district, &stype); err != nil {
				return nil, true, err
			}
			tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: name}, {Text: district}, {Text: stype}}})
		}
	}

	tabs := &screensv1.PageLinkTabs{
		Scrolls: true,
		Tabs: []*screensv1.PageLinkTab{
			{Label: "SSA Risk", Href: CDDrilldownPath + "?drill=risk&issue=no_ssa&fy=" + fy, Active: drill == "risk"},
			{Label: "Low-SSA Districts", Href: CDDrilldownPath + "?drill=district_low_lship&fy=" + fy, Active: drill == "district_low_lship"},
			{Label: "Partners", Href: CDDrilldownPath + "?drill=partner&fy=" + fy, Active: drill == "partner"},
			{Label: "Programme Leads", Href: CDDrilldownPath + "?drill=pl&fy=" + fy, Active: drill == "pl"},
			{Label: "Budget", Href: CDDrilldownPath + "?drill=budget&fy=" + fy, Active: drill == "budget"},
		},
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
	}
	if len(tbl.Rows) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "No records matched this drilldown for FY" + fy + ".",
		}})
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: tbl}})
	}

	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Country Director Analytics",
			Title:       title,
			Description: subtitle,
		},
		WebPath: CDDrilldownPath,
		Blocks:  blocks,
	}, true, nil
}
