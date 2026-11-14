package hrregister

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// metric is one context figure as a view hands it to _metric.
type metric struct {
	label, value, helper, tone string
}

// count is a figure's value as Python's str() writes a count.
func count(n int) string { return strconv.Itoa(n) }

// cell is _cell: a value, or a dash for nothing.
type cell struct{ label, value string }

// action is a button that opens a drawer ({"label", "drawer"}), or with
// href a link to a page ({"label", "href"}).
type action struct{ label, drawer, href string }

// register is everything _render_workspace is given.
type register struct {
	path, title, eyebrow, description string
	metrics                           []metric
	columns                           []string
	rows                              [][]string
	// rowActions are each row's own drawer buttons (none, or one list a row).
	rowActions            [][]action
	actions               []action
	emptyTitle, emptyBody string
	// teamView is a Programme Lead's team register, which sits under My Team
	// rather than Human Capital.
	teamView bool
}

const (
	defaultEmptyTitle = "No records in this scope"
	defaultEmptyBody  = "New records will appear here as the connected workflow progresses."
)

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// breadcrumb is the register's breadcrumb as the feed reads it: Human
// Capital, or My Team for a team register.
func breadcrumb(reg register) *screensv1.PageBlock {
	home := &screensv1.PageLink{Text: "Human Capital", Href: "/dashboard"}
	if reg.teamView {
		home = &screensv1.PageLink{Text: "My Team", Href: "/my-team"}
	}
	return panel("",
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{home}}}},
		text("/"), text(reg.title))
}

func strip(r Role) *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Label: r.Strip.Label, Scrolls: r.Strip.Scrolls}
	for _, t := range r.Strip.Tabs {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

// figures is components/context_metrics.html as the feed reads it: each
// figure once (by its label), under the label the registry draws it with;
// the line under it cut to a second figure, the sentence it was kept as the
// note, and the figure's tone only beside a line that stays.
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
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: title + " context", Metrics: out}}}
}

// records is partials/hr/module_register.html as the feed reads it: the
// register's heading, then the page of records as a table (and, past one
// page, its pager), or the empty state; while a search is on, a way back
// to the register without it.
func records(reg register, query url.Values) []*screensv1.PageBlock {
	heading := []*screensv1.PagePanelItem{}
	if closedschools.StripSpace(query.Get("q")) != "" {
		// "Clear search", back to the register without its search.
		heading = append(heading, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: "Clear search", Href: reg.path}}}}})
	}
	if len(reg.rows) == 0 {
		return []*screensv1.PageBlock{panel("Current operational records", append(heading,
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: reg.emptyTitle}},
			text(reg.emptyBody))...)}
	}
	number, pages := closedschools.PageOf(query.Get("page"), len(reg.rows), rules.PageSize)
	t := &screensv1.PageTable{}
	for _, c := range reg.columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	first, last := (number-1)*rules.PageSize, min(number*rules.PageSize, len(reg.rows))
	withActions := false
	for _, acts := range reg.rowActions[min(first, len(reg.rowActions)):min(last, len(reg.rowActions))] {
		withActions = withActions || len(acts) > 0
	}
	if withActions {
		// The actions column's heading is for screen readers only.
		t.Columns = append(t.Columns, &screensv1.PageColumn{})
	}
	for i, row := range reg.rows[first:last] {
		r := &screensv1.PageRow{}
		for _, v := range row {
			r.Cells = append(r.Cells, &screensv1.PageCell{Text: closedschools.Collapse(v)})
		}
		if withActions {
			r.Cells = append(r.Cells, actionsCell(reg.rowActions, first+i))
		}
		t.Rows = append(t.Rows, r)
	}
	out := []*screensv1.PageBlock{panel("Current operational records", heading...), {Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, pager(number, pages, query))
	}
	return out
}

// actionsCell is a record's own buttons as the feed reads its one button: a
// primary drawer button under the key "button". (No register Go answers yet
// gives a record two actions, which the template draws as a menu.)
func actionsCell(all [][]action, row int) *screensv1.PageCell {
	c := &screensv1.PageCell{}
	if row >= len(all) {
		return c
	}
	for _, a := range all[row] {
		if a.href != "" {
			c.Actions = append(c.Actions, &screensv1.PageAction{Key: "button", Label: a.label, Primary: true, Enabled: true, Href: a.href})
			continue
		}
		c.Actions = append(c.Actions, &screensv1.PageAction{Key: "button", Label: a.label, Primary: true, Enabled: true, Href: a.drawer, Drawer: true})
	}
	return c
}

// pager is the register's own pager (hcos-pagination) as the feed reads it:
// "Page N of M", then Prev and Next, each a link keeping the search and
// read again as its two words without a link (its label and its arrow).
func pager(number, pages int, query url.Values) *screensv1.PageBlock {
	base := "?q=" + urlencode(closedschools.StripSpace(query.Get("q"))) + "&page="
	p := &screensv1.PagePager{Pages: []*screensv1.PagePagerPage{{Label: "Page " + strconv.Itoa(number) + " of " + strconv.Itoa(pages)}}}
	step := func(label, arrow string, to int) {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: label, Href: base + strconv.Itoa(to)},
			&screensv1.PagePagerPage{Label: label}, &screensv1.PagePagerPage{Label: arrow})
	}
	if number > 1 {
		step("Prev", "‹", number-1)
	}
	if number < pages {
		step("Next", "›", number+1)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: p}}
}

// urlencode is Django's |urlencode: urllib.parse.quote(value, safe="/").
func urlencode(value string) string {
	var b strings.Builder
	for _, c := range []byte(value) {
		switch {
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9', strings.IndexByte("_.-~/", c) >= 0:
			b.WriteByte(c)
		default:
			fmt.Fprintf(&b, "%%%02X", c)
		}
	}
	return b.String()
}

// render is _render_workspace as the feed reads the page.
func render(reg register, role Role, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: reg.eyebrow, Title: reg.title, Description: reg.description}
	for _, a := range reg.actions {
		if a.href != "" {
			// A link button is drawn for a role that may open its page; the
			// feed does not read it (only drawer buttons).
			continue
		}
		for _, allowed := range role.Drawers {
			if allowed == a.drawer {
				header.Actions = append(header.Actions, &screensv1.PageAction{
					Key: slug(a.label), Label: a.label, Enabled: true, Href: a.drawer, Drawer: true})
				break
			}
		}
	}
	blocks := []*screensv1.PageBlock{breadcrumb(reg)}
	if role.Strip != nil {
		blocks = append(blocks, strip(role))
	}
	blocks = append(blocks, figures(reg.title, reg.metrics))
	blocks = append(blocks, records(reg, query)...)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: reg.path}
}

// slug is the feed's key for a header button: its label in lower case, each
// run of anything but a–z and 0–9 one underscore.
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
