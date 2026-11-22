package clusteroversight

import (
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
)

// pageParam is the table's own page parameter ({% paginate table.rows
// "rows_page" %}).
const pageParam = "rows_page"

// header is the section's title and description from workspace.SECTIONS,
// with the header's buttons: Download CSV for a reader who may export (the
// section's table in the year, SSA area and view shown, as a CSV), and
// Scoring for a reader who may set the score weights.
func header(section Section, d Doors, fy string, query url.Values) *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "Cluster Oversight",
		Title:       collapse(section.Label),
		Description: collapse(section.Description),
	}
	if d.Export && section.Key != "reports" {
		h.Actions = append(h.Actions, pageheader.Download("Download CSV", pageheader.Href("/cluster-oversight/"+section.Key,
			url.Values{"fy": {fy}, "area": {ssaArea(query)}, "view": {impactView(query)}, "format": {"csv"}})))
	}
	if d.Scoring {
		h.Actions = append(h.Actions, pageheader.Link("Scoring", "/cluster-oversight/scoring"))
	}
	return h
}

// ssaArea is the view's ssa_area: the asked SSA area when it is one, else
// none.
func ssaArea(query url.Values) string {
	area := strings.TrimSpace(query.Get("area"))
	for _, iv := range rules.SSAInterventions {
		if iv[0] == area {
			return area
		}
	}
	return ""
}

// impactView is the view's impact_view: the asked view when it is one of
// IMPACT_VIEWS, else the first.
func impactView(query url.Values) string {
	view := strings.TrimSpace(query.Get("view"))
	if in(rules.ImpactViews, view) {
		return view
	}
	return rules.ImpactViews[0]
}

// sectionTabs is the strip of sections: each a link to its own address in
// the year shown. A section whose records have their own page is a door to
// it, offered to a reader that page lets in. My Clusters is for someone who
// holds a cluster among more than they hold.
func sectionTabs(active, fy string, d Doors, showMine bool) *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	for _, s := range rules.Sections {
		switch {
		case s.Key == "my" && !showMine:
		case s.URL != "":
			if d.Directory {
				tabs = append(tabs, &screensv1.PageLinkTab{Label: collapse(s.Label), Href: "/clusters"})
			}
		default:
			tabs = append(tabs, &screensv1.PageLinkTab{
				Label: collapse(s.Label), Href: "/cluster-oversight/" + s.Key + "?fy=" + fy, Active: s.Key == active,
			})
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs, Scrolls: true}}}
}

// filtersBlock is the page's filters: always fiscal year, plus SSA area on
// the SSA Performance section and View on Impact Analytics.
func filtersBlock(sectionKey, fy string, years []string, query url.Values) *screensv1.PageBlock {
	fyFilter := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: fy}
	for _, y := range years {
		fyFilter.Options = append(fyFilter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	filters := []*screensv1.PageFilter{fyFilter}
	if sectionKey == "ssa" {
		areaFilter := &screensv1.PageFilter{
			Name:  "area",
			Label: "SSA area",
			Value: ssaArea(query),
			Options: []*screensv1.PageFilterOption{
				{Value: "", Label: "All SSA Areas"},
			},
		}
		for _, iv := range rules.SSAInterventions {
			areaFilter.Options = append(areaFilter.Options, &screensv1.PageFilterOption{Value: iv[0], Label: iv[1]})
		}
		filters = append(filters, areaFilter)
	}
	if sectionKey == "impact" {
		viewFilter := &screensv1.PageFilter{
			Name:  "view",
			Label: "View",
			Value: impactView(query),
			Options: []*screensv1.PageFilterOption{
				{Value: "clusters", Label: "Clusters Compared"},
				{Value: "courses", Label: "Training Effectiveness"},
			},
		}
		filters = append(filters, viewFilter)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters}}}
}

// pageNumber is {% paginate %}'s reading of the page asked for: a number
// from one up, the first for anything else; then paginate_rows' clamp to
// the pages there are.
func pageNumber(requested string, total int) (number, pages int) {
	size := rules.TablePageSize
	pages = max(1, (total+size-1)/size)
	number = 1
	if n, ok := clusterpage.PyInt(requested); ok && requested != "" {
		number = max(1, n)
	}
	return min(number, pages), pages
}

// window is pagination.make_pagination_window(current, pages,
// window_size=1): the page numbers the pager shows, 0 for a gap.
func window(current, pages int) []int {
	out := []int{}
	if pages <= 7 {
		for p := 1; p <= pages; p++ {
			out = append(out, p)
		}
		return out
	}
	out = append(out, 1)
	if current-1 > 2 {
		out = append(out, 0)
		for p := current - 1; p < current; p++ {
			out = append(out, p)
		}
	} else {
		for p := 2; p < current; p++ {
			out = append(out, p)
		}
	}
	if current != 1 {
		out = append(out, current)
	}
	if current+1 < pages-1 {
		for p := current + 1; p < current+2; p++ {
			out = append(out, p)
		}
		out = append(out, 0)
	} else {
		for p := current + 1; p < pages; p++ {
			out = append(out, p)
		}
	}
	for _, p := range out {
		if p == pages {
			return out
		}
	}
	return append(out, pages)
}

// carried is {% pager_query %}: every query value the page was opened with
// except the table's own page, kept by each page link. The gateway hands the
// existing application its query in key order, so that is the order here.
func carried(query url.Values) string {
	keys := []string{}
	for key, values := range query {
		if key != pageParam && !in(rules.NotPassedQueryKeys, key) && len(values) > 0 && values[0] != "" {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	out := strings.Builder{}
	for _, key := range keys {
		out.WriteString(url.QueryEscape(key) + "=" + url.QueryEscape(query.Get(key)) + "&")
	}
	return out.String()
}

// pager is components/table_pager.html as the feed reads it.
func pager(number, pages, total, shown int, query url.Values) *screensv1.PagePager {
	first := (number-1)*rules.TablePageSize + 1
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d–%d of %d", first, first+shown-1, total)}
	href := func(page int) string { return "?" + carried(query) + pageParam + "=" + strconv.Itoa(page) }
	if number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev", Href: href(number - 1)})
	}
	for _, n := range window(number, pages) {
		switch {
		case n == 0:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "…"})
		case n == number:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Current: true})
		default:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Href: href(n)})
		}
	}
	if number < pages {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Next", Href: href(number + 1)})
	}
	return p
}

// cellOf is one cell as the template draws it and the feed reads it: a
// figure with schools behind it links to the cluster profile (the cluster's
// own page for its name) for a reader that page lets in; a school name links
// to the school profile; a direct href links to its path.
func cellOf(c cell, d Doors) *screensv1.PageCell {
	out := &screensv1.PageCell{Text: collapse(c.text), Tone: c.tone}
	switch {
	case c.href != "":
		out.Href = c.href
	case c.school != "":
		out.Href = "/schools/" + c.school
	case c.cluster != "" && d.Cluster:
		out.Href = "/clusters/" + c.cluster
		if c.query != "" {
			out.Href += "/profile" + c.query
		}
	}
	return out
}

// tableBlock is the section's table as the feed reads it: fifty rows a
// page, the note under it, and the empty state in place of the rows.
func tableBlock(t table, d Doors, query url.Values) *screensv1.PageBlock {
	out := &screensv1.PageTable{Title: collapse(t.title), Subtitle: collapse(t.summary)}
	if len(t.rows) == 0 {
		out.EmptyMessage = collapse(t.empty)
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: out}}
	}
	cols := t.columns
	if len(cols) == 0 {
		cols = rules.Command.Columns
	}
	for _, column := range cols {
		out.Columns = append(out.Columns, &screensv1.PageColumn{Label: collapse(column.Label), Numeric: column.Numeric})
	}
	number, pages := pageNumber(query.Get(pageParam), len(t.rows))
	start := (number - 1) * rules.TablePageSize
	shown := t.rows[start:min(start+rules.TablePageSize, len(t.rows))]
	for _, row := range shown {
		cells := make([]*screensv1.PageCell, len(row))
		for i, c := range row {
			cells[i] = cellOf(c, d)
		}
		out.Rows = append(out.Rows, &screensv1.PageRow{Cells: cells})
	}
	out.Footnote = collapse(t.note)
	if pages > 1 {
		out.Pager = pager(number, pages, len(t.rows), len(shown), query)
		// The feed takes the first paragraph under the table for its note,
		// and with a pager that is the pager's own "Showing 1–50 of 60".
		out.Footnote = out.Pager.GetSummary()
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: out}}
}
