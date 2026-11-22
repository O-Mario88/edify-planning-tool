package dashboard

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"sync"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

const secondaryViewTTL = 15 * time.Second

type cachedView struct {
	resp      *screensv1.GetPageResponse
	expiresAt time.Time
}

type viewCache struct {
	mu      sync.RWMutex
	entries map[string]cachedView
}

func newViewCache() *viewCache {
	return &viewCache{entries: map[string]cachedView{}}
}

func (c *viewCache) get(key string, now time.Time) (*screensv1.GetPageResponse, bool) {
	if c == nil {
		return nil, false
	}
	c.mu.RLock()
	e, ok := c.entries[key]
	c.mu.RUnlock()
	if !ok || now.After(e.expiresAt) {
		return nil, false
	}
	return e.resp, true
}

func (c *viewCache) set(key string, resp *screensv1.GetPageResponse, now time.Time) {
	if c == nil || resp == nil {
		return
	}
	c.mu.Lock()
	if len(c.entries) >= 500 {
		clear(c.entries)
	}
	c.entries[key] = cachedView{resp: resp, expiresAt: now.Add(secondaryViewTTL)}
	c.mu.Unlock()
}

// Native Go builders for the remaining Programme Lead dashboard views
// (Priorities, Team, Coaching, Programmes, Collaboration) and the CCEO
// Urgent Schools ("operations") view.

func normalizeLeadView(raw string) string {
	v := strings.ToLower(strings.TrimSpace(raw))
	if alias, ok := rules.Lead.ViewAliases[v]; ok {
		v = alias
	}
	if slices.Contains(rules.Lead.Views, v) {
		return v
	}
	return rules.Lead.DefaultView
}

// leadYearFor builds the fiscal-year selector while preserving the active view.
func leadYearFor(fy string, options []string, activeView string) *screensv1.PageBlock {
	filter := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: fy}
	for _, y := range options {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{filter},
		Hidden:  map[string]string{"view": activeView},
	}}}
}

// leadViewsFor renders the Programme Lead view tabs with activeView highlighted.
func leadViewsFor(fy, activeView string) *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Scrolls: true}
	for _, v := range rules.Lead.ViewTabs {
		href := Path + "?" + url.Values{"fy": {fy}, "view": {v[0]}}.Encode()
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{
			Label:  v[1],
			Href:   href,
			Active: v[0] == activeView,
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

func (s *Service) buildLeadSecondaryView(
	ctx context.Context, p auth.Principal, view, fy string, options []string, now time.Time,
) (*screensv1.GetPageResponse, bool, error) {
	cacheKey := p.UserID + "|" + p.ActiveRole + "|" + view + "|" + fy
	if hit, ok := s.cache.get(cacheKey, now); ok {
		return hit, true, nil
	}
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)

	supervised, onTeam, teamIDs, err := leadTeam(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	c, err := readLeadCtx(ctx, s.db, p, fy, now, today, supervised, onTeam)
	if err != nil {
		return nil, true, err
	}
	pulse, err := s.readPulse(ctx, c)
	if err != nil {
		return nil, true, err
	}
	cards, err := s.attention(ctx, c, pulseEscalations{pulse.escalations.ToDecide, pulse.escalations.Overdue})
	if err != nil {
		return nil, true, err
	}

	blocks := []*screensv1.PageBlock{
		leadYearFor(fy, options, view),
		pulse.strip(fy),
		leadViewsFor(fy, view),
	}

	var extra []*screensv1.PageBlock
	switch view {
	case "priorities":
		extra, err = s.buildLeadPriorities(ctx, c, cards, teamIDs, today)
	case "team":
		extra, err = s.buildLeadTeamView(ctx, supervised, fy, today)
	case "coaching":
		extra, err = s.buildLeadCoachingView(ctx, c, supervised, today)
	case "programmes":
		extra, err = s.buildLeadProgrammesView(ctx, c, fy)
	case "collaboration":
		extra, err = s.buildLeadCollaborationView(ctx, c, fy, today)
	default:
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, extra...)
	resp := &screensv1.GetPageResponse{
		Header:    leadHeader(cards, fy),
		Blocks:    blocks,
		WebPath:   Path,
		Selection: myplan.ActivityBar(),
	}
	s.cache.set(cacheKey, resp, now)
	return resp, true, nil
}

func (s *Service) buildLeadPriorities(
	ctx context.Context, c *leadCtx, cards []card, teamIDs []string, today time.Time,
) ([]*screensv1.PageBlock, error) {
	var links []*screensv1.PageLink
	for _, cd := range cards {
		links = append(links, &screensv1.PageLink{Text: cd.action, Href: cd.url})
	}
	if len(links) == 0 {
		links = []*screensv1.PageLink{
			{Text: "Open escalations", Href: "/escalations"},
			{Text: "Open Team Planning Oversight", Href: "/team-planning-oversight/"},
			{Text: "Open Partner Oversight", Href: "/partner-oversight/"},
		}
	}
	summary := fmt.Sprintf("%d priority item(s) requiring leadership action in FY %s.", len(cards), c.fy)
	if len(cards) == 0 {
		summary = fmt.Sprintf("No critical escalations or overdue approvals pending in FY %s.", c.fy)
	}
	attentionPanel := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title:    "Leadership Attention Queue",
		Subtitle: summary,
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}},
		},
	}}}

	allOwners := append([]string{}, myplan.OwnerIDs(c.p)...)
	allOwners = append(allOwners, teamIDs...)
	tbl := &screensv1.PageTable{
		Title: "Overdue & Returned Team Activities",
		Columns: []*screensv1.PageColumn{
			{Label: "Planned Date"},
			{Label: "Activity"},
			{Label: "School / Cluster"},
			{Label: "Status"},
			{Label: "Owner"},
		},
	}
	if len(allOwners) > 0 {
		rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.planned_date::text, ''), COALESCE(a.activity_type, ''),
       COALESCE(s.name, cl.name, '—'), COALESCE(s.id, ''), COALESCE(a.status, ''),
       COALESCE(NULLIF(u.name, ''), NULLIF(sp.title, ''), 'Staff')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN staff_profile sp ON sp.id = a.responsible_staff_id OR sp.user_id = a.responsible_staff_id
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE a.deleted_at IS NULL
  AND a.responsible_staff_id = ANY($1)
  AND (
    a.status = ANY($2)
    OR (a.planned_date < $3 AND NOT COALESCE(a.status = ANY($4), false))
  )
ORDER BY a.planned_date ASC NULLS LAST
LIMIT 25`, allOwners, rules.Lead.CCEOBacklogStatuses, today.Format(time.DateOnly), rules.Lead.CompletedStatuses)
		if err != nil {
			return nil, fmt.Errorf("dashboard: priorities table: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id, planned, kind, place, schoolID, status, owner string
			if err := rows.Scan(&id, &planned, &kind, &place, &schoolID, &status, &owner); err != nil {
				return nil, fmt.Errorf("dashboard: priorities scan: %w", err)
			}
			placeCell := &screensv1.PageCell{Text: place}
			if schoolID != "" {
				placeCell.Href = "/schools/" + schoolID
			}
			tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: first10(planned)},
				{Text: myplan.TypeLabel(kind)},
				placeCell,
				{Text: status, Badge: true, Tone: "warning"},
				{Text: owner},
			}})
		}
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	if len(tbl.Rows) == 0 {
		return []*screensv1.PageBlock{attentionPanel, {Kind: &screensv1.PageBlock_Empty{Empty: "No overdue or returned activities across your team."}}}, nil
	}
	return []*screensv1.PageBlock{attentionPanel, {Kind: &screensv1.PageBlock_Table{Table: tbl}}}, nil
}

func (s *Service) buildLeadTeamView(
	ctx context.Context, supervised []officer, fy string, today time.Time,
) ([]*screensv1.PageBlock, error) {
	tbl := &screensv1.PageTable{
		Title: fmt.Sprintf("Team Delivery & Workload — FY %s", fy),
		Columns: []*screensv1.PageColumn{
			{Label: "Officer"},
			{Label: "Schools Assigned"},
			{Label: "FY Planned"},
			{Label: "Completed"},
			{Label: "Overdue"},
			{Label: "Completion"},
		},
	}
	day := today.Format(time.DateOnly)
	staffIDs := make([]string, 0, len(supervised))
	ownerToStaff := make(map[string]string, len(supervised)*2)
	allOwnerIDs := make([]string, 0, len(supervised)*2)
	for _, o := range supervised {
		staffIDs = append(staffIDs, o.staffID)
		for _, id := range o.ids() {
			ownerToStaff[id] = o.staffID
			allOwnerIDs = append(allOwnerIDs, id)
		}
	}

	schoolCounts := map[string]int{}
	if len(staffIDs) > 0 {
		if sRows, err := s.db.Query(ctx, `
SELECT account_owner_id, count(*)
FROM school
WHERE deleted_at IS NULL AND operational_status = ANY($1) AND account_owner_id = ANY($2)
GROUP BY account_owner_id`, rules.Lead.OperatingStatuses, staffIDs); err == nil {
			for sRows.Next() {
				var owner string
				var cnt int
				if sRows.Scan(&owner, &cnt) == nil {
					schoolCounts[owner] = cnt
				}
			}
			sRows.Close()
		}
	}

	type actStats struct{ planned, completed, overdue int }
	actByStaff := map[string]actStats{}
	if len(allOwnerIDs) > 0 {
		if aRows, err := s.db.Query(ctx, `
SELECT responsible_staff_id,
  count(*) FILTER (WHERE NOT COALESCE(status = ANY($2), false)),
  count(*) FILTER (WHERE status = ANY($3)),
  count(*) FILTER (WHERE planned_date < $4 AND NOT COALESCE(status = ANY($3), false) AND NOT COALESCE(status = ANY($2), false))
FROM activity
WHERE deleted_at IS NULL AND fy = $5 AND responsible_staff_id = ANY($1)
GROUP BY responsible_staff_id`,
			allOwnerIDs, rules.Lead.NotInPlanStatuses, rules.Lead.CompletedStatuses, day, fy); err == nil {
			for aRows.Next() {
				var owner string
				var st actStats
				if aRows.Scan(&owner, &st.planned, &st.completed, &st.overdue) == nil {
					sid := ownerToStaff[owner]
					cur := actByStaff[sid]
					cur.planned += st.planned
					cur.completed += st.completed
					cur.overdue += st.overdue
					actByStaff[sid] = cur
				}
			}
			aRows.Close()
		}
	}

	for _, o := range supervised {
		schools := schoolCounts[o.staffID]
		st := actByStaff[o.staffID]
		planned, completed, overdue := st.planned, st.completed, st.overdue
		pct := "0%"
		if planned > 0 {
			pct = fmt.Sprintf("%d%%", (completed*100)/planned)
		}
		tone := "success"
		if overdue > 0 {
			tone = "warning"
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: o.name, Href: Path + "?" + url.Values{"fy": {fy}, "view": {"week"}, "who": {o.staffID}}.Encode()},
			{Text: fmt.Sprint(schools)},
			{Text: fmt.Sprint(planned)},
			{Text: fmt.Sprint(completed)},
			{Text: fmt.Sprint(overdue), Badge: overdue > 0, Tone: tone},
			{Text: pct},
		}})
	}
	links := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Team Management Shortcuts",
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: "Team Planning Oversight", Href: "/team-planning-oversight/"},
			{Text: "Team Availability & Leave", Href: "/leave/team-availability"},
			{Text: "Team Targets", Href: "/team-targets"},
			{Text: "My Team Roster", Href: "/my-team/"},
		}}}}},
	}}}
	if len(tbl.Rows) == 0 {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Empty{Empty: "No supervised officers assigned to your team yet."}}, links}, nil
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: tbl}}, links}, nil
}

func (s *Service) buildLeadCoachingView(
	ctx context.Context, c *leadCtx, supervised []officer, today time.Time,
) ([]*screensv1.PageBlock, error) {
	flags, overdueFlags, err := s.cdFlags(ctx, c)
	if err != nil {
		return nil, err
	}
	feedback, coachingNotes, err := s.regionalNotes(ctx, c)
	if err != nil {
		return nil, err
	}

	kpis := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Coaching & Support Signals",
		Metrics: []*screensv1.PageMetric{
			{Label: "CD Quality Flags", Value: fmt.Sprint(flags), Note: fmt.Sprintf("%d overdue", overdueFlags), Href: "/quality-checks"},
			{Label: "Regional Coaching Notes", Value: fmt.Sprint(coachingNotes), Note: "Unread notes", Href: "/cce-leadership/coaching"},
			{Label: "Training Feedback", Value: fmt.Sprint(feedback), Note: "Pending acknowledgement", Href: "/cce-leadership/feedback"},
			{Label: "Officers Coached", Value: fmt.Sprint(len(supervised)), Note: "Active team", Href: "/my-team/"},
		},
	}}}

	tbl := &screensv1.PageTable{
		Title: "Recent Field Debriefs & Coaching Visits",
		Columns: []*screensv1.PageColumn{
			{Label: "Date"},
			{Label: "Officer"},
			{Label: "Focus / Summary"},
		},
	}
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(dd.date::text, ''), COALESCE(NULLIF(u.name, ''), 'Field Officer'),
       COALESCE(NULLIF(dd.key_wins, ''), NULLIF(dd.challenges, ''), 'Field debrief submitted')
FROM daily_debrief dd
LEFT JOIN "user" u ON u.id = dd.user_id
WHERE dd.date >= $1
ORDER BY dd.date DESC
LIMIT 15`, today.AddDate(0, 0, -30).Format(time.DateOnly))
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var dt, who, summary string
			if scanErr := rows.Scan(&dt, &who, &summary); scanErr == nil {
				if len(summary) > 120 {
					summary = summary[:117] + "..."
				}
				tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
					{Text: first10(dt)},
					{Text: who},
					{Text: summary},
				}})
			}
		}
	}
	actions := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Coaching & Field Debrief Actions",
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: "Open Field Debriefs", Href: "/debriefs"},
			{Text: "Open Regional Coaching", Href: "/cce-leadership/coaching"},
			{Text: "Open Training Feedback", Href: "/cce-leadership/feedback"},
			{Text: "Open Quality Checks", Href: "/quality-checks"},
		}}}}},
	}}}
	if len(tbl.Rows) == 0 {
		return []*screensv1.PageBlock{kpis, {Kind: &screensv1.PageBlock_Empty{Empty: "No field debriefs recorded in the last 30 days."}}, actions}, nil
	}
	return []*screensv1.PageBlock{kpis, {Kind: &screensv1.PageBlock_Table{Table: tbl}}, actions}, nil
}

func (s *Service) buildLeadProgrammesView(ctx context.Context, c *leadCtx, fy string) ([]*screensv1.PageBlock, error) {
	tbl := &screensv1.PageTable{
		Title: fmt.Sprintf("Programme Reach & SSA Coverage by Cohort — FY %s", fy),
		Columns: []*screensv1.PageColumn{
			{Label: "School Cohort"},
			{Label: "Active Schools"},
			{Label: "SSA Assessed"},
			{Label: "Avg SSA Score"},
		},
	}
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(NULLIF(s.school_type, ''), 'unclassified') AS cohort,
       count(DISTINCT s.id) AS total_schools,
       count(DISTINCT sr.school_id) AS assessed_schools,
       COALESCE(round(avg(sr.average_score)::numeric, 2), 0) AS avg_ssa
FROM school s
LEFT JOIN LATERAL (
  SELECT r.school_id, r.average_score
  FROM ssa_record r
  WHERE r.school_id = s.id AND r.deleted_at IS NULL
    AND r.verification_status = 'confirmed' AND r.fy = $1
  ORDER BY r.date_of_ssa DESC LIMIT 1
) sr ON true
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($2)
GROUP BY 1
ORDER BY total_schools DESC`, fy, rules.Lead.OperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("dashboard: programmes cohort: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var cohort string
		var total, assessed int
		var avg float64
		if err := rows.Scan(&cohort, &total, &assessed, &avg); err != nil {
			return nil, fmt.Errorf("dashboard: programmes scan: %w", err)
		}
		avgStr := "—"
		if assessed > 0 {
			avgStr = fmt.Sprintf("%.2f / 10", avg)
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: strings.ReplaceAll(cohort, "_", " "), Badge: true, Tone: "primary"},
			{Text: fmt.Sprint(total)},
			{Text: fmt.Sprintf("%d (%d%%)", assessed, safePct(assessed, total))},
			{Text: avgStr},
		}})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	actTbl := &screensv1.PageTable{
		Title: fmt.Sprintf("Programme Activities by Type — FY %s", fy),
		Columns: []*screensv1.PageColumn{
			{Label: "Activity Type"},
			{Label: "Planned"},
			{Label: "Completed / Verified"},
		},
	}
	aRows, err := s.db.Query(ctx, `
SELECT COALESCE(activity_type, 'other'),
       count(*) FILTER (WHERE NOT COALESCE(status = ANY($2), false)),
       count(*) FILTER (WHERE status = ANY($3))
FROM activity
WHERE deleted_at IS NULL AND fy = $1
GROUP BY 1
ORDER BY 2 DESC
LIMIT 15`, fy, rules.Lead.NotInPlanStatuses, rules.Lead.CompletedStatuses)
	if err == nil {
		defer aRows.Close()
		for aRows.Next() {
			var kind string
			var planned, done int
			if scanErr := aRows.Scan(&kind, &planned, &done); scanErr == nil {
				actTbl.Rows = append(actTbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
					{Text: myplan.TypeLabel(kind)},
					{Text: fmt.Sprint(planned)},
					{Text: fmt.Sprint(done)},
				}})
			}
		}
	}
	links := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Programme Oversight Views",
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: "Cluster Oversight", Href: "/cluster-oversight/"},
			{Text: "Core School Oversight", Href: "/core-schools-oversight"},
			{Text: "Clusters Directory", Href: "/clusters"},
			{Text: "Country Map", Href: Path + "?fy=" + url.QueryEscape(fy) + "&view=map"},
		}}}}},
	}}}
	actBlock := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: actTbl}}
	if len(actTbl.Rows) == 0 {
		actBlock = &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: fmt.Sprintf("No programme activities logged in FY %s yet.", fy)}}
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Table{Table: tbl}},
		actBlock,
		links,
	}, nil
}

func (s *Service) buildLeadCollaborationView(
	ctx context.Context, c *leadCtx, fy string, today time.Time,
) ([]*screensv1.PageBlock, error) {
	tbl := &screensv1.PageTable{
		Title: fmt.Sprintf("Training Partner Delivery & Coordination — FY %s", fy),
		Columns: []*screensv1.PageColumn{
			{Label: "Partner"},
			{Label: "Planned"},
			{Label: "Completed"},
			{Label: "Overdue"},
		},
	}
	day := today.Format(time.DateOnly)
	rows, err := s.db.Query(ctx, `
SELECT p.name,
       count(a.id) FILTER (WHERE a.deleted_at IS NULL AND a.fy = $1 AND NOT COALESCE(a.status = ANY($2), false)),
       count(a.id) FILTER (WHERE a.deleted_at IS NULL AND a.fy = $1 AND a.status = ANY($3)),
       count(a.id) FILTER (WHERE a.deleted_at IS NULL AND a.fy = $1 AND a.planned_date < $4 AND NOT COALESCE(a.status = ANY($5), false))
FROM partner p
LEFT JOIN activity a ON a.facilitating_partner_id = p.id
WHERE p.deleted_at IS NULL
GROUP BY p.id, p.name
ORDER BY 2 DESC, p.name ASC
LIMIT 25`, fy, rules.Lead.NotInPlanStatuses, rules.Lead.CompletedStatuses, day, rules.Lead.PartnerSettledStatuses)
	if err != nil {
		return nil, fmt.Errorf("dashboard: collaboration partners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var name string
		var planned, done, overdue int
		if err := rows.Scan(&name, &planned, &done, &overdue); err != nil {
			return nil, fmt.Errorf("dashboard: collaboration scan: %w", err)
		}
		tone := "success"
		if overdue > 0 {
			tone = "warning"
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: name},
			{Text: fmt.Sprint(planned)},
			{Text: fmt.Sprint(done)},
			{Text: fmt.Sprint(overdue), Badge: overdue > 0, Tone: tone},
		}})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	links := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Collaboration & Communication Channels",
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: "Partner Oversight", Href: "/partner-oversight/"},
			{Text: "Escalations", Href: "/escalations"},
			{Text: "Messages", Href: "/messages"},
			{Text: "Decision Log", Href: "/decision-log"},
		}}}}},
	}}}
	if len(tbl.Rows) == 0 {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Empty{Empty: "No active training partners configured."}}, links}, nil
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: tbl}}, links}, nil
}

// buildOfficerOperationsView renders the CCEO "Urgent schools" (/dashboard?view=operations)
// tab natively in Go.
func (s *Service) buildOfficerOperationsView(
	ctx context.Context, p auth.Principal, owners []string, today time.Time,
) (*screensv1.GetPageResponse, bool, error) {
	home, err := s.readHome(ctx, owners, today)
	if err != nil {
		return nil, true, err
	}

	tabs := &screensv1.PageLinkTabs{Scrolls: true}
	for _, v := range rules.Officer.Views {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{
			Label:  v[1],
			Href:   Path + "?view=" + v[0],
			Active: v[0] == "operations",
		})
	}

	tbl := &screensv1.PageTable{
		Title: "Urgent Schools Needing Attention",
		Columns: []*screensv1.PageColumn{
			{Label: "School ID"},
			{Label: "School"},
			{Label: "District"},
			{Label: "Cohort"},
			{Label: "Latest SSA"},
			{Label: "Overdue Items"},
		},
	}
	day := today.Format(time.DateOnly)
	rows, err := s.db.Query(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(d.name, '—'),
       COALESCE(s.school_type, 'client'),
       COALESCE(round(ssa.average_score::numeric, 2)::text, '—'),
       count(a.id) FILTER (WHERE a.deleted_at IS NULL AND a.planned_date < $2 AND NOT COALESCE(a.status = ANY($3), false)) AS overdue_cnt
FROM school s
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN LATERAL (
  SELECT r.average_score FROM ssa_record r
  WHERE r.school_id = s.id AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'
  ORDER BY r.date_of_ssa DESC LIMIT 1
) ssa ON true
LEFT JOIN activity a ON a.school_id = s.id
WHERE s.deleted_at IS NULL
  AND s.operational_status IN ('active', 'reopened')
  AND ($1 = '' OR s.account_owner_id = $1)
GROUP BY s.id, s.school_id, s.name, d.name, s.school_type, ssa.average_score
ORDER BY overdue_cnt DESC, ssa.average_score ASC NULLS FIRST, s.name ASC
LIMIT 30`, p.StaffProfileID, day, rules.Officer.DoneStatuses)
	if err != nil {
		return nil, true, fmt.Errorf("dashboard: urgent schools: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, code, name, district, cohort, ssaScore string
		var overdue int
		if err := rows.Scan(&id, &code, &name, &district, &cohort, &ssaScore, &overdue); err != nil {
			return nil, true, fmt.Errorf("dashboard: urgent schools scan: %w", err)
		}
		tone := "success"
		if overdue > 0 {
			tone = "danger"
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code},
			{Text: name, Href: "/schools/" + id},
			{Text: district},
			{Text: strings.ReplaceAll(cohort, "_", " "), Badge: true, Tone: "primary"},
			{Text: ssaScore},
			{Text: fmt.Sprint(overdue), Badge: overdue > 0, Tone: tone},
		}})
	}
	if err := rows.Err(); err != nil {
		return nil, true, err
	}
	tableBlock := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: tbl}}
	if len(tbl.Rows) == 0 {
		tableBlock = &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: "No urgent schools found in your portfolio."}}
	}

	blocks := []*screensv1.PageBlock{
		home.strip(),
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		tableBlock,
	}
	return &screensv1.GetPageResponse{
		Header:    home.header(today),
		Blocks:    blocks,
		WebPath:   Path,
		Selection: myplan.ActivityBar(),
	}, true, nil
}

func safePct(part, total int) int {
	if total <= 0 {
		return 0
	}
	return (part * 100) / total
}
