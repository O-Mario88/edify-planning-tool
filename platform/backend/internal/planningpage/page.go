package planningpage

import (
	"fmt"
	"net/url"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func collapse(text string) string { return strings.Join(strings.Fields(text), " ") }

// header is pages/planning/index.html's header as the feed reads it: the
// buttons beside the lead, Export (the page's own query, as a CSV), Plan
// Field Event for a role that may add a field event, and Recent changes.
func header(doors Doors, query url.Values) *screensv1.PageHeader {
	actions := []*screensv1.PageAction{
		pageheader.Download("Export", pageheader.QueryHref(Path, query, rules.NotPassedQueryKeys, "export", "csv")),
	}
	if doors.FieldEvent {
		actions = append(actions, pageheader.Drawer("Plan Field Event", "/work-plan/add", false))
	}
	actions = append(actions, pageheader.Drawer("Recent changes", "/planning/recent-changes", false))
	return &screensv1.PageHeader{
		Eyebrow:     "Planning",
		Title:       "Planning",
		Description: "Plan school visits, cluster activities, and partner assignments based on SSA readiness and school needs.",
		Actions:     actions,
	}
}

type option struct{ value, label string }

// selectOf is one <select> as the feed reads it: the selected option, else
// the first.
func selectOf(name, label, selected string, options []option) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label}
	for i, o := range options {
		if i == 0 {
			f.Value = o.value
		}
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: collapse(o.label)})
	}
	for _, o := range options {
		if o.value == selected {
			f.Value = o.value
			break
		}
	}
	return f
}

// captioned gives a select the short word the page draws beside it.
func captioned(f *screensv1.PageFilter, caption string) *screensv1.PageFilter {
	f.Caption = caption
	return f
}

// formFilters are the filter form's selects in page order; the form's
// state is what the tabs link to.
func formFilters(f filterState, years []string, districts, staff []option, support bool) []*screensv1.PageFilter {
	fy := []option{}
	for _, y := range years {
		fy = append(fy, option{y, "FY " + y})
	}
	quarters := []option{{"Q1", "Q1"}, {"Q2", "Q2"}, {"Q3", "Q3"}, {"Q4", "Q4"}}
	readiness := []option{{"All", "All Readiness"}}
	for _, c := range rules.ReadinessChoices {
		readiness = append(readiness, option{c[0], c[1]})
	}
	ssa := []option{{"All", "All SSA"}}
	for _, c := range rules.SSAStatusChoices {
		ssa = append(ssa, option{c[0], c[1]})
	}
	group := "name"
	if f.group == "owner" {
		group = "owner"
	}
	list := []*screensv1.PageFilter{
		captioned(selectOf("fy", "Fiscal year", f.fy, fy), "FY"),
		selectOf("quarter", "Quarter", f.quarter, quarters),
		selectOf("district", "District", f.district, append([]option{{"All", "All Districts"}}, districts...)),
		selectOf("staff", "Staff", f.staff, append([]option{{"All", "All Staff"}}, staff...)),
		captioned(selectOf("group", "Group schools", group, []option{{"owner", "By PL & CCEO"}, {"name", "By name"}}), "Group"),
		captioned(selectOf("planning_readiness", "Planning readiness", f.readiness, readiness), "Readiness"),
	}
	if support {
		menu := []option{}
		for _, pair := range rules.SupportFilters {
			menu = append(menu, option{pair[0], pair[1]})
		}
		list = append(list, captioned(selectOf("support", "Support and planning status", f.support, menu), "Show"))
	}
	return append(list, captioned(selectOf("ssa_status", "SSA status", f.ssaStatus, ssa), "SSA"))
}

// tabs are partials/planning/tabs.html as links: the form's values as they
// stand (empty ones left out), its tab changed.
func tabs(f filterState, filters []*screensv1.PageFilter) *screensv1.PageBlock {
	type pair struct{ key, value string }
	state := []pair{{"tab", f.tab}}
	for _, filter := range filters {
		if filter.GetValue() != "" {
			state = append(state, pair{filter.GetName(), filter.GetValue()})
		}
	}
	link := func(tab string) string {
		parts := []string{}
		for _, p := range state {
			value := p.value
			if p.key == "tab" {
				value = tab
			}
			if value == "" {
				continue
			}
			parts = append(parts, url.QueryEscape(p.key)+"="+url.QueryEscape(value))
		}
		return "?" + strings.Join(parts, "&")
	}
	out := &screensv1.PageLinkTabs{}
	for _, t := range [][2]string{{"client", "Client Schools"}, {"core", "Core Schools"}, {"clusters", "Clusters"},
		{"partner", "Assigned to Partner"}, {"scheduled", "Scheduled / In My Plan"}} {
		out.Tabs = append(out.Tabs, &screensv1.PageLinkTab{Label: t[1], Href: link(t[0]), Active: f.tab == t[0]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: out}}
}

// factTone is records.FACT_TONES: a fact's colour by the words in its
// holder's classes.
func factTone(classes string) string {
	for _, pair := range [][2]string{{"danger", "alert"}, {"critical", "alert"}, {"warning", "caution"},
		{"needs_attention", "caution"}, {"success", "good"}, {"healthy", "good"},
		{"is-positive", "good"}, {"is-planned", "info"}, {"is-attention", "caution"}} {
		if strings.Contains(classes, pair[0]) {
			return pair[1]
		}
	}
	return ""
}

// row is partials/planning/school_row.html as the feed reads it.
func row(s school, d Doors, support bool, fy string) *screensv1.PageRow {
	b := s.badges
	if b == nil {
		b = &schoolplanning.Badges{}
	}
	name := &screensv1.PageCell{Text: collapse(s.Name)}
	if d.OpenSchool && s.Name != "" && strings.TrimSpace(s.ID) != "" {
		name.Href = "/schools/" + s.ID
	}
	cluster := &screensv1.PageCell{}
	switch {
	case s.ClusterID != "" && s.ClusterName != "Cluster missing":
		cluster.Text, cluster.Href = collapse(s.ClusterName), "/clusters/"+s.ClusterID
	case s.ClusterName == "Cluster missing":
		cluster.Text = "Cluster missing"
	default:
		cluster.Text = "Not clustered"
	}
	gates := schoolprofile.GateRules()
	lock := s.gate.LockStateLabel(gates)
	if lock == "" {
		lock = "—"
	}
	cells := []*screensv1.PageCell{
		{Text: collapse(s.Code)}, name, cluster,
		{Text: clusterpage.JoinedChips(b.VisitChips()), Pills: clusterpage.ChipPills(b.VisitChips())},
		{Text: clusterpage.JoinedChips(b.TrainingChips(), b.ClusterMeetingChips()),
			Pills: clusterpage.ChipPills(b.TrainingChips(), b.ClusterMeetingChips())},
		{Text: lock, Pills: clusterpage.LockPills(s.gate, gates)},
	}
	if support {
		who := "Staff"
		if s.partner {
			who = "Partner"
		}
		cells = append(cells, &screensv1.PageCell{Text: who})
	}
	actions := []*screensv1.PageAction{}
	if d.Schedule {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Schedule", Enabled: true,
			Href: "/planning/schedule-modal?school_id=" + s.Code, Drawer: true})
	}
	if d.AssignPartner && s.gate.CanAssignPartner {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Assign", Enabled: true,
			Href: "/planning/assign-partner-modal?school_id=" + s.Code, Drawer: true})
	}
	cells = append(cells, &screensv1.PageCell{Actions: actions})
	r := &screensv1.PageRow{Cells: cells, PickId: s.Code}

	fact := func(label, value, href, tone string) *screensv1.PageFact {
		return &screensv1.PageFact{Label: label, Value: collapse(value), Href: href, Tone: tone}
	}
	district, districtHref := "—", ""
	if s.HasDistrictRow {
		district = s.District
	}
	if s.DistrictID != "" {
		districtHref = "/districts/" + s.DistrictID
	}
	clusterName := s.ClusterName
	if clusterName == "" {
		clusterName = "Not assigned"
	}
	enrolment := "—"
	if s.Enrolment != nil {
		enrolment = itoa(*s.Enrolment)
	}
	staffHref := ""
	if s.OwnerID != "" {
		staffHref = "/staff/" + s.OwnerID
	}
	average, tone := schooldirectory.SSAAverage(s.scores)
	ssa := "Not assessed"
	if average != nil {
		ssa = clusterpage.ScoreText(*average) + "/10"
	}
	ssaTone := ""
	if tone != "" {
		ssaTone = factTone("is-" + tone)
	}
	countTone := func(n int) string {
		if n > 0 {
			return "good"
		}
		return "caution"
	}
	clusterHref := ""
	if s.ClusterID != "" && clusterName != "Not assigned" && clusterName != "Cluster missing" {
		clusterHref = "/clusters/" + s.ClusterID
	}
	r.Details = []*screensv1.PageFact{
		fact("District", district, districtHref, ""),
		fact("Shipping Address", orDash(s.Shipping), "", ""),
		fact("School Type", schoolprofile.SchoolTypeLabel(s.Type), "", ""),
		fact("Cluster", clusterName, clusterHref, ""),
		fact("Enrollment", enrolment, "", ""),
		fact("Phone", orDefault(s.Phone, "No phone"), "", ""),
		fact("Primary Contact", orDash(s.Contact), "", ""),
		fact("Staff Name", s.ownerName, staffHref, ""),
		fact("SSA", ssa, "", ssaTone),
		fact("Visit", itoa(s.visits), "", countTone(s.visits)),
		fact("Training", itoa(s.trainings), "", countTone(s.trainings)),
	}
	if support {
		next := "—"
		if s.next != nil {
			next = fmt.Sprintf("%s · %d %s", s.next.Label, s.next.Day.Day(), s.next.Day.Format("Jan"))
		}
		r.Details = append(r.Details, fact("Next Activity", next, "", ""))
	}
	// The row opens on the school's profile, or else on the first link of
	// its details (the district's, then the owner's).
	switch {
	case d.OpenSchool:
		r.DetailsHref = "/schools/" + s.ID
	case districtHref != "":
		r.DetailsHref = districtHref
	default:
		r.DetailsHref = staffHref
	}
	items := []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: "Latest confirmed assessment · FY " + fy}}}
	groups, has := schooldirectory.SSAGroups(s.scores)
	if !has {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "No confirmed SSA scores are available yet."}})
	} else {
		items = append(items, clusterpage.ScoreGroupItems(groups)...)
	}
	r.DetailBlocks = []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Intervention scores", Subtitle: "SSA detail", Items: items,
	}}}}
	return r
}

func orDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func orDash(value string) string { return orDefault(value, "—") }

// groupRow is an owner group's heading row.
func groupRow(label string, n int) *screensv1.PageRow {
	plural := "s"
	if n == 1 {
		plural = ""
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: collapse(fmt.Sprintf("%s %d school%s", label, n, plural))}}}
}

// window is pagination.make_pagination_window(page, total, 1); 0 is "...".
func window(page, total int) []int {
	if total <= 7 {
		out := []int{}
		for p := 1; p <= total; p++ {
			out = append(out, p)
		}
		return out
	}
	out := []int{1}
	if page-1 > 2 {
		out = append(out, 0)
		for p := page - 1; p < page; p++ {
			out = append(out, p)
		}
	} else {
		for p := 2; p < page; p++ {
			out = append(out, p)
		}
	}
	if page != 1 {
		out = append(out, page)
	}
	if page+1 < total-1 {
		out = append(out, page+1, 0)
	} else {
		for p := page + 1; p < total; p++ {
			out = append(out, p)
		}
	}
	has := false
	for _, p := range out {
		has = has || p == total
	}
	if !has {
		out = append(out, total)
	}
	return out
}

// pageLink is the table's pager address for a page, its values as written.
func pageLink(f filterState, page int) string {
	return fmt.Sprintf("/planning?page=%d&per_page=%d&fy=%s&quarter=%s&district=%s&sub_county=%s&staff=%s&school_type=%s"+
		"&planning_readiness=%s&ssa_status=%s&cluster_status=%s&partner=%s&support=%s&q=%s&tab=%s&group=%s",
		page, f.perPage, f.fy, f.quarter, f.district, f.subCounty, f.staff, f.schoolType, f.readiness, f.ssaStatus,
		f.clusterStatus, f.partner, f.support, f.q, f.tab, f.group)
}

// pager is the table's footer as the feed reads it.
func pager(f filterState, total, pages int, noun string) (summary string, out []*screensv1.PagePagerPage) {
	start, end := 0, min(f.page*f.perPage, total)
	if total > 0 {
		start = (f.page-1)*f.perPage + 1
	}
	summary = fmt.Sprintf("Showing %d–%d of %d %s", start, end, total, noun)
	if f.page > 1 {
		out = append(out, &screensv1.PagePagerPage{Label: "Prev", Href: pageLink(f, f.page-1)})
	}
	for _, p := range window(f.page, pages) {
		if p == 0 {
			out = append(out, &screensv1.PagePagerPage{Label: "..."})
			continue
		}
		out = append(out, &screensv1.PagePagerPage{Label: itoa(p), Href: pageLink(f, p), Current: p == f.page})
	}
	if f.page < pages {
		out = append(out, &screensv1.PagePagerPage{Label: "Next", Href: pageLink(f, f.page+1)})
	}
	return summary, out
}

// pageSizes are the pager's rows-a-page chooser (school_table.html).
var pageSizes = []string{"15", "20", "50"}

// pagerBlock is the list's pager strip: "Showing …", its pages and the
// "15 / page" chooser (the one selected, else the first).
func pagerBlock(f filterState, summary string, pages []*screensv1.PagePagerPage) *screensv1.PageBlock {
	size := []option{}
	for _, n := range pageSizes {
		size = append(size, option{n, n + " / page"})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: &screensv1.PagePager{
		Summary: summary, Pages: pages, Size: selectOf("per_page", "Per page", itoa(f.perPage), size),
	}}}
}

// emptyBlocks are the list's empty card, read whole (its message and the
// sentence around its link), and the pager strip under it.
func emptyBlocks(f filterState, anyClustered bool, summary string, pages []*screensv1.PagePagerPage) []*screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Text{Text: "No planning records match your filters."}},
		{Kind: &screensv1.PagePanelItem_Text{Text: "Clear filters or adjust your search."}},
	}
	if !anyClustered {
		items = []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: "No schools have been clustered yet."}},
			{
				Kind:      &screensv1.PagePanelItem_Text{Text: "Planning works on clustered schools. Every school is still in the School Directory — add them to a cluster and they appear here."},
				TextLinks: []*screensv1.PageLink{{Text: "School Directory", Href: "/schools"}},
			},
		}
	}
	return []*screensv1.PageBlock{panelOf(items), pagerBlock(f, summary, pages)}
}

// emptyMessageBlocks are a tab's empty card whose message stands alone
// (Assigned to Partner's, the Clusters tab's) and the pager strip.
func emptyMessageBlocks(f filterState, message, summary string, pages []*screensv1.PagePagerPage) []*screensv1.PageBlock {
	return []*screensv1.PageBlock{
		panelOf([]*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: message}}}),
		pagerBlock(f, summary, pages),
	}
}

func panelOf(items []*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}}
}

// selection is the floating bar's forms that open a drawer.
func selection(d Doors) *screensv1.PageSelection {
	actions := []*screensv1.PageSelectionAction{}
	if d.AssignPartner {
		actions = append(actions, &screensv1.PageSelectionAction{Label: "Assign to partner", Href: "/planning/bulk-assign-partner-drawer", Param: "school_ids"})
	}
	if d.BulkSchedule {
		actions = append(actions, &screensv1.PageSelectionAction{Label: "Schedule visit", Href: "/planning/bulk-schedule-drawer", Param: "school_ids"})
	}
	if len(actions) == 0 {
		return nil
	}
	return &screensv1.PageSelection{Noun: "schools selected", Actions: actions}
}

// activityBar is partials/activities/selection_bar.html, the Scheduled
// tab's bar for ticked calendar entries; the feed finds it before the bar
// for ticked schools.
func activityBar() *screensv1.PageSelection {
	return &screensv1.PageSelection{Noun: "activities selected", Actions: []*screensv1.PageSelectionAction{
		{Label: "Reschedule", Href: "/activity-selection/reschedule", Param: "ids", Joined: true},
		{Label: "Cancel", Href: "/activity-selection/cancel", Param: "ids", Joined: true},
	}}
}
