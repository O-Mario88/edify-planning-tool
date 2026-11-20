package partnerassigned

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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The partner portal's three lists, as the existing feed reads them:
// Assigned Schools (/partner/schools: partner_views.partner_schools_view,
// pages/partner/schools.html), the Activity Log (/partner/activities:
// partner_activities_view, pages/partner/activities.html) and Assigned
// Activities (/partner/assignments: partner_assignments_view,
// pages/partner/assignments.html), each over the work and assignments of
// the organisation the login acts as. Scheduling and returning stay with
// their drawers.

// The portal's paths.
const (
	PortalSchoolsPath     = "/partner/schools"
	PortalActivitiesPath  = "/partner/activities"
	PortalAssignmentsPath = "/partner/assignments"
)

var logStatuses = [][2]string{
	{"", "All"}, {"scheduled", "Scheduled"}, {"completed", "Completed"}, {"ia_verified", "IA Verified"}, {"cancelled", "Cancelled"},
}

func portalHeader(eyebrow, title, description string) *screensv1.PageHeader {
	return &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: description,
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
}

func portalPage(h *screensv1.PageHeader, path string, blocks ...*screensv1.PageBlock) *screensv1.GetPageResponse {
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, Tabs: []*screensv1.PageTab{},
		Dialogs: []*screensv1.PageDialog{}, WebPath: path}
}

func plainPanel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: title, Badges: []*screensv1.PageBadge{}, Items: items}}}
}

func drawerLinks(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	for _, l := range ls {
		l.Drawer = true
	}
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func table(columns []string, numericFrom int, rows []*screensv1.PageRow) *screensv1.PageBlock {
	t := &screensv1.PageTable{Rows: rows}
	for i, c := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: i >= numericFrom})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func badge(text string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: text, Tone: "primary", Badge: true}
}

// portal answers the three lists.
func (s *Service) portal(ctx context.Context, p auth.Principal, path string, partners []string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	switch path {
	case PortalSchoolsPath:
		out, err := s.portalSchools(ctx, p, partners, query)
		return out, true, err
	case PortalActivitiesPath:
		out, err := s.activityLog(ctx, p, partners, query)
		return out, true, err
	}
	out, err := s.portalAssignments(ctx, partners)
	return out, true, err
}

// portalSchools is partner_schools_view: the live schools the organisation
// has work at that was not called off, by name, fifty a page.
func (s *Service) portalSchools(ctx context.Context, p auth.Principal, partners []string, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(s.school_id, 'None'), s.name, COALESCE(d.id, ''), COALESCE(d.name, ''), COALESCE(sc.name, ''), COALESCE(s.enrollment, 0),
  COALESCE(s.current_fy_ssa_status, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
WHERE s.deleted_at IS NULL AND s.id IN (SELECT a.school_id FROM activity a
  WHERE a.assigned_partner_id = ANY($1) AND a.deleted_at IS NULL AND a.status <> ALL($2))
ORDER BY s.name`, partners, rules.CalledOffStatuses)
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the organisation's schools: %w", err)
	}
	type held struct {
		code, name, districtID, district, subCounty, ssa string
		enrollment                                       int64
	}
	all, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (held, error) {
		var h held
		return h, r.Scan(&h.code, &h.name, &h.districtID, &h.district, &h.subCounty, &h.enrollment, &h.ssa)
	})
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the organisation's schools: %w", err)
	}
	h := portalHeader("Partner Portal", "Assigned Schools", strconv.Itoa(len(all))+" school(s) your organization works with.")
	if len(all) == 0 {
		return portalPage(h, PortalSchoolsPath, plainPanel("",
			text("Schools appear here once activities are assigned to your organization."))), nil
	}
	pg := tablepager.Paginate(len(all), rules.PageSize, query, "schools_page")
	out := []*screensv1.PageRow{}
	openDistricts := slices.Contains(rules.ProfileLinkRoles["districts"], p.ActiveRole)
	for _, x := range all[pg.Start:pg.End] {
		district := &screensv1.PageCell{Text: "—"}
		if x.district != "" {
			district.Text = collapse(x.district)
			if openDistricts {
				district.Href = "/districts/" + x.districtID
			}
		}
		sub := x.subCounty
		if sub == "" {
			sub = "—"
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: x.code}, {Text: collapse(x.name)}, district, {Text: collapse(sub)},
			{Text: closedschools.Comma(x.enrollment)}, badge(stafflogs.StatusLabel(x.ssa)),
		}})
	}
	blocks := []*screensv1.PageBlock{table([]string{"School ID", "School", "District", "Sub-county", "Enrollment", "SSA Status"}, 4, out)}
	if p := tablepager.Panel(len(all), rules.PageSize, query, "schools_page"); p != nil {
		blocks = append(blocks, p)
	}
	return portalPage(h, PortalSchoolsPath, blocks...), nil
}

// logged is one activity on the Activity Log.
type logged struct {
	id, kind, status, schoolID, school, clusterID, cluster string
	// code is the live school's School ID, as the web fills it in.
	code    string
	planned *time.Time
}

// activityLog is partner_activities_view: the assignments awaiting the
// organisation's date, then its work (the status asked for, else what was
// not called off), latest planned first, sixty of it, fifty a page.
func (s *Service) activityLog(ctx context.Context, p auth.Principal, partners []string, query url.Values) (*screensv1.GetPageResponse, error) {
	status := query.Get("status")
	where, args := "a.status <> ALL($2)", []any{partners, rules.CalledOffStatuses}
	if status != "" {
		where, args = "a.status = $2", []any{partners, status}
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(s.id, ''), COALESCE(s.name, ''),
  COALESCE(CASE WHEN s.deleted_at IS NULL THEN s.school_id END, ''), COALESCE(c.id, ''), COALESCE(c.name, ''), a.planned_date
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.assigned_partner_id = ANY($1) AND a.deleted_at IS NULL AND `+where+`
ORDER BY a.planned_date DESC NULLS FIRST, a.id DESC LIMIT `+strconv.Itoa(rules.LogLimit), args...)
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the activity log: %w", err)
	}
	work, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (logged, error) {
		var l logged
		return l, r.Scan(&l.id, &l.kind, &l.status, &l.schoolID, &l.school, &l.code, &l.clusterID, &l.cluster, &l.planned)
	})
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the activity log: %w", err)
	}
	awaiting, err := s.awaiting(ctx, partners, "a.scheduled_date ASC NULLS LAST, a.created_at ASC", rules.LogLimit)
	if err != nil {
		return nil, err
	}
	// The select reads as its chosen option: a status it does not offer
	// leaves "All" chosen.
	filter := &screensv1.PageFilter{Name: "status", Label: "Status"}
	for _, o := range logStatuses {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if o[0] == status {
			filter.Value = status
		}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{filter}}}}}
	if len(awaiting) > 0 {
		var items []*screensv1.PagePanelItem
		for _, a := range awaiting {
			// school_link / cluster_link: a link for those who open such
			// profiles, which the feed reads as the line's link.
			name, kind, id := a.cluster, "clusters", a.clusterID
			if a.schoolID != "" {
				name, kind, id = a.school, "schools", a.schoolID
			}
			line := collapse(name)
			if a.focus != "" {
				line += " · " + stafflogs.StatusLabel(a.focus)
			}
			place := text(line)
			if name != "" && slices.Contains(rules.ProfileLinkRoles[kind], p.ActiveRole) {
				place.TextLinks = []*screensv1.PageLink{{Text: collapse(name), Href: "/" + kind + "/" + id}}
			}
			items = append(items, text(or(a.course, or(a.item, "Approved Activity choice"))), place,
				text("Yet to Schedule"), drawerLinks(
					&screensv1.PageLink{Text: "Return", Href: "/partner/assignments/" + a.id + "/return-drawer"},
					&screensv1.PageLink{Text: "Schedule", Href: "/partner/assignments/" + a.id + "/schedule-drawer"}))
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: "Assignments awaiting your schedule"}},
			plainPanel("", items...))
	}
	h := portalHeader("Partner Portal", "Activity Log", strconv.Itoa(len(work))+" recent activities assigned to your organization.")
	if len(work) == 0 {
		empty := text("Activities assigned to your organization will appear here.")
		if len(awaiting) == 0 {
			blocks = append(blocks, plainPanel("", empty))
			return portalPage(h, PortalActivitiesPath, blocks...), nil
		}
		// Without a table the feed reads the card as one panel: the
		// assignments' heading its title, the first assignment's name its
		// line, and the empty note.
		first := or(awaiting[0].course, or(awaiting[0].item, "Approved Activity choice"))
		blocks = append(blocks[:1], &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Assignments awaiting your schedule", Subtitle: collapse(first), Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{empty}}}})
		return portalPage(h, PortalActivitiesPath, blocks...), nil
	}
	pg := tablepager.Paginate(len(work), rules.PageSize, query, "activities_page")
	out := []*screensv1.PageRow{}
	for _, w := range work[pg.Start:pg.End] {
		place := &screensv1.PageCell{Text: "—"}
		switch {
		case w.schoolID != "":
			place = &screensv1.PageCell{Text: collapse(w.school), Href: "/schools/" + w.schoolID}
		case w.clusterID != "":
			place = &screensv1.PageCell{Text: collapse(w.cluster), Href: "/clusters/" + w.clusterID}
		}
		kind, ok := rules.ActivityTypes[w.kind]
		if !ok {
			kind = w.kind
		}
		date := ""
		if w.planned != nil {
			date = w.planned.Format("02 Jan 2006")
		}
		code := &screensv1.PageCell{Text: "—"}
		if w.schoolID != "" {
			// The school's ID as the web fills in its school_code tag.
			code = &screensv1.PageCell{Text: closedschools.SchoolCode(w.code)}
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			code, place, {Text: kind}, {Text: date}, badge(stafflogs.StatusLabel(w.status)),
		}})
	}
	blocks = append(blocks, table([]string{"School ID", "School / Cluster", "Type", "Date", "Status"}, 4, out))
	if p := tablepager.Panel(len(work), rules.PageSize, query, "activities_page"); p != nil {
		blocks = append(blocks, p)
	}
	return portalPage(h, PortalActivitiesPath, blocks...), nil
}

// held is one assignment with what the lists show of it.
type held struct {
	id, status, schoolID, school, clusterID, cluster, focus, course, item string
}

// awaiting are the organisation's assignments awaiting its date, in order,
// to limit.
func (s *Service) awaiting(ctx context.Context, partners []string, order string, limit int) ([]held, error) {
	return s.assignments(ctx, partners, "a.status = ANY($2)", []any{partners, rules.AwaitingStatuses}, order, limit)
}

func (s *Service) assignments(ctx context.Context, partners []string, where string, args []any, order string, limit int) ([]held, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.status, COALESCE(s.id, ''), COALESCE(s.name, ''), COALESCE(c.id, ''), COALESCE(c.name, ''),
  COALESCE(a.focus_intervention, ''), COALESCE(tc.display_name, ''), COALESCE(ci.display_name, '')
FROM partner_assignment a
LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE a.partner_id = ANY($1) AND `+where+`
ORDER BY `+order+` LIMIT `+strconv.Itoa(limit), args...)
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the organisation's assignments: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (held, error) {
		var h held
		return h, r.Scan(&h.id, &h.status, &h.schoolID, &h.school, &h.clusterID, &h.cluster, &h.focus, &h.course, &h.item)
	})
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the organisation's assignments: %w", err)
	}
	return out, nil
}

// portalAssignments is partner_assignments_view: the newest two hundred of
// the organisation's assignments, those awaiting its date and those it
// scheduled.
func (s *Service) portalAssignments(ctx context.Context, partners []string) (*screensv1.GetPageResponse, error) {
	all, err := s.assignments(ctx, partners, "true", []any{partners}, "a.created_at DESC", rules.AssignmentsLimit)
	if err != nil {
		return nil, err
	}
	var pending, scheduled []*screensv1.PagePanelItem
	var waiting, planned int
	for _, a := range all {
		name := or(a.school, or(a.cluster, "Field work"))
		switch {
		case slices.Contains(rules.AwaitingStatuses, a.status):
			waiting++
			pending = append(pending, text(collapse(name)))
			if line := or(a.course, a.item); line != "" {
				pending = append(pending, text(collapse(line)))
			}
			pending = append(pending, drawerLinks(&screensv1.PageLink{Text: "Schedule",
				Href: "/partner/assignments/" + a.id + "/schedule-drawer"}))
		case a.status == "partner_scheduled":
			planned++
			scheduled = append(scheduled, text(collapse(name)), text("On My Plan"))
		}
	}
	if waiting == 0 {
		pending = []*screensv1.PagePanelItem{text("New work assigned to your organisation appears here for you to schedule.")}
	}
	if planned == 0 {
		scheduled = []*screensv1.PagePanelItem{text("Scheduled work appears on My Plan.")}
	}
	h := portalHeader("Field Work", "Assigned Activities",
		"Work assigned to your organisation. Schedule it — the budget is created from the CD Cost Catalogue automatically and the activity moves to My Plan.")
	return portalPage(h, PortalAssignmentsPath,
		plainPanel("Awaiting Scheduling "+strconv.Itoa(waiting), pending...),
		plainPanel("Scheduled "+strconv.Itoa(planned), scheduled...)), nil
}
