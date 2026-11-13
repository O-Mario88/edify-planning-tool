package ccelead

import (
	"net/url"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// metric is one figure as a view hands it to _metric.
type metric struct{ label, value, helper, tone string }

// action is a drawer button (a header's, or a record's own), or with href a
// link to a page.
type action struct{ label, drawer, href string }

// register is everything _render is given.
type register struct {
	path, title, eyebrow, description, registerTitle string
	notice                                           string
	metrics                                          []metric
	columns                                          []string
	rows                                             [][]string
	rowActions                                       [][]action
	actions                                          []action
	emptyTitle, emptyBody                            string
	// filters are the register's own selects; after are the cards drawn
	// under it (the Regional Lead's rhythm).
	filters []*screensv1.PageFilter
	after   []*screensv1.PageBlock
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// slug is the feed's key for a header button.
func slug(label string) string {
	var b strings.Builder
	gap := false
	for _, r := range strings.ToLower(label) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			if gap && b.Len() > 0 {
				b.WriteByte('_')
			}
			gap = false
			b.WriteRune(r)
			continue
		}
		gap = true
	}
	return b.String()
}

// figures is components/context_metrics.html as the feed reads it (the HR
// registers' rule: each figure once, the line under it kept only as a short
// second figure, else the note; its tone only beside a line that stays).
func figures(title string, metrics []metric) *screensv1.PageBlock {
	seen := map[string]bool{}
	out := []*screensv1.PageMetric{}
	for _, m := range metrics {
		label := m.label
		if l, ok := rules.MetricLabels[label]; ok {
			label = l
		}
		key := strings.ToLower(strings.TrimSpace(label))
		if label == "" || seen[key] {
			continue
		}
		seen[key] = true
		helper, note := m.helper, ""
		if helper != "" {
			if brief := schoolprofile.BriefHelper(helper); brief != helper {
				helper, note = brief, m.helper
			}
		}
		tone := ""
		if helper != "" {
			tone = m.tone
		}
		value := m.value
		if value == "" {
			value = "—"
		}
		out = append(out, &screensv1.PageMetric{Label: label, Value: value, Helper: helper, Note: note, Tone: tone})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: title + " at a glance", Metrics: out}}}
}

// render is _render as the feed reads workspace.html: the notice, the
// figures, the register's heading, then the page of records (its own
// buttons in an unlabelled last column) and, past one page, the shared pager;
// without records, the feed reads the empty card as a one-cell table.
func render(reg register, role Role, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: reg.eyebrow, Title: reg.title, Description: reg.description}
	for _, a := range reg.actions {
		for _, allowed := range role.Drawers {
			if allowed == a.drawer {
				header.Actions = append(header.Actions, &screensv1.PageAction{Key: slug(a.label), Label: a.label, Enabled: true, Href: a.drawer, Drawer: true})
				break
			}
		}
	}
	blocks := []*screensv1.PageBlock{}
	if role.Strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: role.Strip.Label, Scrolls: role.Strip.Scrolls}
		for _, t := range role.Strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	if reg.notice != "" {
		blocks = append(blocks, panel("", text(reg.notice)))
	}
	blocks = append(blocks, figures(reg.title, reg.metrics), panel(reg.registerTitle))
	if len(reg.filters) > 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: reg.filters}}})
	}
	if len(reg.rows) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			EmptyMessage: reg.emptyTitle,
			Rows: []*screensv1.PageRow{{Cells: []*screensv1.PageCell{
				{Text: closedschools.Collapse(reg.title + " " + reg.emptyTitle + " " + reg.emptyBody)}}}},
		}}})
		blocks = append(blocks, reg.after...)
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: reg.path}
	}
	number, pages := closedschools.PageOf(query.Get("register_page"), len(reg.rows), rules.PageSize)
	t := &screensv1.PageTable{}
	for _, c := range reg.columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{})
	first, last := (number-1)*rules.PageSize, min(number*rules.PageSize, len(reg.rows))
	for i, row := range reg.rows[first:last] {
		r := &screensv1.PageRow{}
		for _, v := range row {
			r.Cells = append(r.Cells, &screensv1.PageCell{Text: closedschools.Collapse(v)})
		}
		cell := &screensv1.PageCell{}
		acts := reg.rowActions[first+i]
		for _, a := range acts {
			// One action is the record's button; two or more are its Actions
			// menu.
			pa := &screensv1.PageAction{Key: "button", Label: a.label, Primary: true, Enabled: true, Href: a.drawer, Drawer: true}
			if a.href != "" {
				pa.Href, pa.Drawer = a.href, false
			}
			if len(acts) > 1 {
				pa.Key, pa.Primary = "menu", false
			}
			cell.Actions = append(cell.Actions, pa)
		}
		r.Cells = append(r.Cells, cell)
		t.Rows = append(t.Rows, r)
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("register_page", number, pages, len(reg.rows), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	blocks = append(blocks, reg.after...)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: reg.path}
}
