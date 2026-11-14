package projectcapacity

import (
	"net/url"
	"slices"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	ruleNote  = "A project with no allocations is open: any staff member may add its schools. Once you set the first allocation, only staff with an allocation can add them."
	emptyNote = "Projects you coordinate appear here once they are running."
)

func collapse(text string) string { return closedschools.Collapse(text) }

func header(projects []project, selected string) *screensv1.PageHeader {
	h := &screensv1.PageHeader{Eyebrow: "Special Projects", Title: "Project Capacity",
		Description: "How many schools each staff member may add to each of your projects."}
	if len(projects) > 0 {
		href := "/projects/capacity/set"
		if selected != "" {
			href += "?project=" + selected
		}
		h.Actions = []*screensv1.PageAction{{Key: "set_staff_capacity", Label: "+ Set Staff Capacity", Enabled: true, Href: href, Drawer: true}}
	}
	return h
}

func linkTabs(tabs *screensv1.PageLinkTabs) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

// projectTabs is one project a tab, when there is more than one.
func projectTabs(projects []project, selected string) *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Scrolls: true}
	for _, p := range projects {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: collapse(p.Name), Href: Path + "?project=" + p.ID, Active: p.ID == selected})
	}
	return linkTabs(tabs)
}

func textPanel(text string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: text}}}}}}
}

// sectionHead is the project's card head as the feed reads it: its name and
// code as the title, and its Actions menu as links. The figures under the
// name are a definition list the feed does not read.
func sectionHead(p project) *screensv1.PageBlock {
	title := p.Name
	if p.Code != "" {
		title += " " + p.Code
	}
	links := &screensv1.PageLinks{Links: []*screensv1.PageLink{
		{Text: "Manage capacity", Href: "/projects/capacity/set?project=" + p.ID, Drawer: true},
		{Text: "View schools", Href: "/projects/monitoring?project=" + p.ID},
		{Text: "Project details", Href: "/projects/" + p.ID},
	}}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: collapse(title), Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: links}}}}}}
}

// utilization is Allocation.utilization through |floatformat:"-1": the
// share used to one place, without a trailing ".0".
func utilization(a allocation) string {
	if a.Maximum == 0 {
		return "0%"
	}
	v := schooldirectory.PyRound1(float64(a.Assigned) / float64(a.Maximum) * 100)
	return strconv.FormatFloat(v, 'f', -1, 64) + "%"
}

// status is the allocation's chip: Blocked on a project that takes no new
// schools, else Full, Near capacity or Available.
func status(a allocation, blocked bool) string {
	switch {
	case blocked:
		return "Blocked"
	case a.Assigned >= a.Maximum:
		return "Full"
	case float64(a.Assigned) >= float64(a.Maximum)*rules.NearCapacityShare:
		return "Near capacity"
	}
	return "Available"
}

// visits is the person's counted visits this year, against their role's
// ceiling when they have one, and how many are past it; a cell past it is
// read in the danger tone of its "over" mark.
func visits(a allocation) *screensv1.PageCell {
	planned := strconv.Itoa(a.Planned)
	if a.Ceiling == 0 {
		return &screensv1.PageCell{Text: planned}
	}
	cell := &screensv1.PageCell{Text: planned + " / " + strconv.Itoa(a.Ceiling)}
	if over := a.Planned - a.Ceiling; over > 0 {
		cell.Text += " " + strconv.Itoa(over) + " over"
		cell.Tone = "danger"
	}
	return cell
}

func row(role Role, a allocation, blocked bool) *screensv1.PageRow {
	name := &screensv1.PageCell{Text: collapse(a.StaffName), Strong: true}
	if role.StaffLinks && a.StaffName != "" && a.StaffID != "" {
		name.Href = "/staff/" + url.PathEscape(a.StaffID)
	}
	plain := func(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		name,
		plain(strconv.Itoa(a.Maximum)),
		plain(strconv.Itoa(a.Assigned)),
		{Text: strconv.Itoa(max(a.Maximum-a.Assigned, 0)), Strong: true},
		plain(utilization(a)),
		visits(a),
		plain(status(a, blocked)),
		{Actions: []*screensv1.PageAction{{Key: "menu", Label: "Edit capacity", Enabled: true,
			Href: "/projects/capacity/" + a.ID + "/edit", Drawer: true}}},
	}}
}

// table is the open project's allocations, one page of them, and the pager
// past one page.
func table(role Role, p project, allocations []allocation, fy string, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, c := range []struct {
		label   string
		numeric bool
	}{
		{"Staff Name", false}, {"Maximum Schools", true}, {"Assigned Schools", true}, {"Remaining", true},
		{"Utilization", true}, {"Visits Planned (FY" + fy + ")", true}, {"Status", false}, {"Action", true},
	} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c.label, Numeric: c.numeric})
	}
	blocked := !slices.Contains(rules.OpenStatuses, p.Status)
	param := "staff_page-" + p.ID
	number, pages := closedschools.PageOf(query.Get(param), len(allocations), rules.PageSize)
	for _, a := range allocations[(number-1)*rules.PageSize : min(number*rules.PageSize, len(allocations))] {
		t.Rows = append(t.Rows, row(role, a, blocked))
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(param, number, pages, len(allocations), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return out
}

// page is the whole answer.
func page(role Role, projects []project, selected string, allocations []allocation, fy string, query url.Values) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if role.Strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: role.Strip.Label, Scrolls: role.Strip.Scrolls}
		for _, t := range role.Strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, linkTabs(tabs))
	}
	if len(projects) > 1 {
		blocks = append(blocks, projectTabs(projects, selected))
	}
	i := slices.IndexFunc(projects, func(p project) bool { return p.ID == selected })
	if i < 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyNote}})
	} else {
		blocks = append(blocks, textPanel(ruleNote), sectionHead(projects[i]))
		if len(allocations) > 0 {
			blocks = append(blocks, table(role, projects[i], allocations, fy, query)...)
		}
	}
	return &screensv1.GetPageResponse{Header: header(projects, selected), Blocks: blocks, WebPath: Path}
}
