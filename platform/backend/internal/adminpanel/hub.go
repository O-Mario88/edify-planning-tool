package adminpanel

import (
	"context"
	"fmt"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// HubPath is the Admin Dashboard (extended_views.admin_panel_view,
// pages/admin/index.html): the user directory's figures, the data quality
// and workflow links, the actions centre and the live alerts (schools with
// unmatched staff, cost-bearing work without cost lines).
const HubPath = "/admin-panel"

type hubFigures struct {
	users, active, invited, suspended, unmatchedSchools, missingLines int
}

// missingLinesWhere is missing_cost_lines_count's predicate over activity a
// (its paired visit pv): live, not exempt, not a pair or online training,
// with no cost line, and carrying cost by its estimate or its dated
// catalogue item. Each exclusion is false where Django's would be on a NULL.
const missingLinesWhere = `a.deleted_at IS NULL AND a.status <> ALL($1)
  AND NOT COALESCE((a.activity_type = 'in_school_training' AND a.paired_school_visit_id IS NOT NULL
      AND pv.deleted_at IS NULL AND NOT (pv.status = ANY($2))), FALSE)
  AND NOT COALESCE((a.activity_type = 'in_school_training' AND a.paired_school_visit_id IS NOT NULL
      AND NOT (a.status = ANY($3))), FALSE)
  AND NOT COALESCE((a.activity_type = ANY($4) AND a.programme_delivery_mode = $5), FALSE)
  AND NOT EXISTS (SELECT 1 FROM activity_schedule_cost_line l WHERE l.activity_id = a.id)
  AND (COALESCE(a.est_cost_cents, 0) > 0 OR (a.catalogue_item_id IS NOT NULL AND a.scheduled_date IS NOT NULL))`

func (s *Service) hubFigures(ctx context.Context) (hubFigures, error) {
	var f hubFigures
	m := rules.MissingLines
	err := s.db.QueryRow(ctx, `SELECT
  (SELECT count(*) FROM "user" WHERE deleted_at IS NULL),
  (SELECT count(*) FROM "user" WHERE deleted_at IS NULL AND status = 'active'),
  (SELECT count(*) FROM "user" WHERE deleted_at IS NULL AND status = 'pending_invited'),
  (SELECT count(*) FROM "user" WHERE deleted_at IS NULL AND status = 'suspended'),
  (SELECT count(*) FROM school WHERE account_owner_status = 'unmatched'),
  (SELECT count(*) FROM activity a LEFT JOIN activity pv ON pv.id = a.paired_school_visit_id WHERE `+missingLinesWhere+`)`,
		m.ExemptStatuses, m.CompanionGoneStatuses, m.RepriceablePairStatuses, m.OnlineTrainingTypes, m.OnlineMode,
	).Scan(&f.users, &f.active, &f.invited, &f.suspended, &f.unmatchedSchools, &f.missingLines)
	if err != nil {
		return f, fmt.Errorf("adminpanel: counting the dashboard's figures: %w", err)
	}
	return f, nil
}

func plural(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

func linkItem(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func titled(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: title, Badges: []*screensv1.PageBadge{}, Items: items}}}
}

func (s *Service) hub(ctx context.Context) (*screensv1.GetPageResponse, bool, error) {
	f, err := s.hubFigures(ctx)
	if err != nil {
		return nil, true, err
	}
	h := header("Administration", "Admin Dashboard System Control", "Platform configuration, user directories, and data integrity center")
	h.Actions = []*screensv1.PageAction{
		{Key: "add_user", Label: "Add User", Enabled: true, Href: "/admin-panel/users"},
		{Key: "review_staff_queue", Label: "Review Staff Queue", Enabled: true, Href: "/admin-panel/staff-setup-queue"},
	}
	var alerts []*screensv1.PagePanelItem
	if f.unmatchedSchools > 0 {
		alerts = append(alerts, text("Unmatched staff queue pending"),
			text(strconv.Itoa(f.unmatchedSchools)+" school"+plural(f.unmatchedSchools, "", "s")+
				" with unmatched staff. Please review the setup queue to link school files with real users."))
	}
	if f.missingLines > 0 {
		alerts = append(alerts, text("Broken workflow warning"),
			text(strconv.Itoa(f.missingLines)+" activit"+plural(f.missingLines, "y", "ies")+
				" scheduled are currently missing cost catalogue entries."))
	}
	if f.unmatchedSchools == 0 && f.missingLines == 0 {
		alerts = append(alerts, text("No active alerts"), text("Staff matching and cost catalogue coverage are both clean."))
	}
	alerts = append(alerts, linkItem(&screensv1.PageLink{Text: "View System Audit Trail", Href: "/admin-panel/audit-log"}))
	action := func(title, line string) *screensv1.PageBlock { return titled("", text(title), text(line)) }
	return page(h, HubPath,
		titled("User Directory Health"),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Performance overview",
			Metrics: []*screensv1.PageMetric{
				{Label: "Total Users", Value: strconv.Itoa(f.users)}, {Label: "Active", Value: strconv.Itoa(f.active)},
			}}}},
		titled("", text("Pending Invites: "+strconv.Itoa(f.invited)), text("Suspended: "+strconv.Itoa(f.suspended))),
		titled("Data Quality Snapshot",
			linkItem(&screensv1.PageLink{Text: "Pending", Href: "/admin-panel/staff-setup-queue", Caption: "Unmatched Staff"},
				&screensv1.PageLink{Text: "Scanner", Href: "/admin-panel/data-quality-center", Caption: "Quality Center"}),
			text("Resolve unmatched staff names from file imports to unlock planning routes.")),
		titled("Workflow Rules Health",
			linkItem(&screensv1.PageLink{Text: "Active", Href: WorkflowRulesPath, Caption: "Workflow Rules"},
				&screensv1.PageLink{Text: "Integrity", Href: "/system-health", Caption: "System Health"}),
			text("System health scanners run continuously to flag broken relations and orphan records.")),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: "Administrative Actions Center"}},
		action("Roles & Permissions", "Manage feature gates, permission matrices, and user access levels"),
		action("Page Access Matrix", "Verify role-specific route parameters and security groups"),
		action("School Upload History", "Audit school and SSA file batch imports with rollback triggers"),
		action("District & Region Setup", "Define geographical coordinates, regions, and regional bounds"),
		titled("System Alerts Live", alerts...),
	), true, nil
}
