package teamperformance

import (
	"regexp"
	"strconv"
	"strings"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The page is written as the templates write it, as a tree of elements
// (templates/pages/team_performance/index.html and its partials), and read
// into blocks by the same rules the existing feed reads the rendered HTML
// with (apps.mobile_feed.page_blocks and css_charts): the part of them this
// page reaches. The shared components (the filter bar, the section tabs and
// the KPI strips) are drawn as their blocks directly.

// node is one element of the page, or (pre) a component already read.
type node struct {
	tag      string
	classes  map[string]bool
	attrs    map[string]string
	children []any // string or *node
	parent   *node
	pre      *screensv1.PageBlock
	// later is the part a lazy section loads (hx-get with a later trigger):
	// built when the walker reaches it, nil when that request is not found.
	later func() *node
}

func el(tag, class string, children ...any) *node {
	n := &node{tag: tag, classes: map[string]bool{}, attrs: map[string]string{}}
	for _, c := range strings.Fields(class) {
		n.classes[c] = true
	}
	n.add(children...)
	return n
}

// attr sets attributes: attr("href", "?x", "title", "t").
func (n *node) attr(kv ...string) *node {
	for i := 0; i+1 < len(kv); i += 2 {
		n.attrs[kv[i]] = kv[i+1]
	}
	return n
}

func (n *node) add(children ...any) *node {
	for _, c := range children {
		switch v := c.(type) {
		case nil:
		case string:
			if v != "" {
				n.children = append(n.children, v)
			}
		case *node:
			if v != nil {
				v.parent = n
				n.children = append(n.children, v)
			}
		case []*node:
			for _, x := range v {
				n.add(x)
			}
		case []any:
			n.add(v...)
		default:
			panic("teamperformance: node child")
		}
	}
	return n
}

func preBlock(b *screensv1.PageBlock) *node {
	n := el("div", "")
	n.pre = b
	return n
}

func (n *node) has(class string) bool { return n.classes[class] }

func (n *node) get(name string) string { return n.attrs[name] }

func (n *node) nodes() []*node {
	out := []*node{}
	var walk func(*node)
	walk = func(x *node) {
		for _, c := range x.children {
			if child, ok := c.(*node); ok {
				out = append(out, child)
				walk(child)
			}
		}
	}
	walk(n)
	return out
}

func (n *node) find(test func(*node) bool) *node {
	for _, x := range n.nodes() {
		if test(x) {
			return x
		}
	}
	return nil
}

func (n *node) findAll(test func(*node) bool) []*node {
	out := []*node{}
	for _, x := range n.nodes() {
		if test(x) {
			out = append(out, x)
		}
	}
	return out
}

func (n *node) elements() []*node {
	out := []*node{}
	for _, c := range n.children {
		if child, ok := c.(*node); ok {
			out = append(out, child)
		}
	}
	return out
}

var silent = map[string]bool{"script": true, "style": true, "svg": true, "noscript": true, "template": true}

// text is Node.text: the element's text, whitespace collapsed, what only a
// screen reader hears left out.
func (n *node) text() string { return n.textOf(true) }

func (n *node) textOf(shown bool) string {
	var b strings.Builder
	var collect func(*node)
	collect = func(x *node) {
		for _, c := range x.children {
			switch v := c.(type) {
			case string:
				b.WriteString(v)
			case *node:
				if silent[v.tag] || (shown && v.has("sr-only")) {
					continue
				}
				collect(v)
			}
		}
	}
	collect(n)
	return strings.Join(strings.Fields(b.String()), " ")
}

func inside(x, ancestor *node) bool {
	for ; x != nil; x = x.parent {
		if x == ancestor {
			return true
		}
	}
	return false
}

// ── The walk (page_blocks._blocks) ──────────────────────────────────────────

func walk(n *node, out []*screensv1.PageBlock) []*screensv1.PageBlock {
	for _, child := range n.elements() {
		if silent[child.tag] {
			continue
		}
		if child.pre != nil {
			out = append(out, child.pre)
			continue
		}
		if child.later != nil {
			if part := child.later(); part != nil {
				out = walk(part, out)
				continue
			}
		}
		if several := areaCard(child); several != nil {
			out = append(out, several...)
			continue
		}
		if b := blockOf(child); b != nil {
			out = append(out, b)
		} else if holdsBlocks(child) || holdsKnown(child) {
			out = walk(child, out)
		} else if b := fallback(child); b != nil {
			out = append(out, b)
		}
	}
	return out
}

func blockOf(n *node) *screensv1.PageBlock {
	if n.tag == "table" {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: readTable(n)}}
	}
	if n.has("edify-empty-state") {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyMessage(n)}}
	}
	return nil
}

func holdsBlocks(n *node) bool {
	return n.find(func(x *node) bool { return x.pre != nil || x.tag == "table" }) != nil
}

func holdsKnown(n *node) bool {
	return n.find(func(x *node) bool { return x.has("edify-empty-state") || x.later != nil || x.pre != nil }) != nil
}

func fallback(n *node) *screensv1.PageBlock {
	if n.tag == "form" || n.tag == "dialog" || n.tag == "template" {
		return nil
	}
	text := n.text()
	if (n.tag == "h2" || n.tag == "h3") && strings.IndexFunc(text, unicode.IsLetter) >= 0 {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: text}}
	}
	if len(strings.Fields(text)) < 2 {
		return nil
	}
	p := readPanel(n)
	if len(p.Items) == 0 && p.Title == "" {
		p.Items = []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: text}}}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
}

func emptyMessage(n *node) string {
	empty := n
	if !n.has("edify-empty-state") {
		empty = n.find(func(x *node) bool { return x.has("edify-empty-state") })
	}
	if empty == nil {
		return ""
	}
	if m := empty.find(func(x *node) bool { return x.has("edify-empty-state__message") }); m != nil {
		return m.text()
	}
	return empty.text()
}

// ── Tables (page_blocks._table, a bare table) ───────────────────────────────

func readTable(table *node) *screensv1.PageTable {
	out := &screensv1.PageTable{}
	head := table.find(func(x *node) bool { return x.tag == "thead" })
	if head != nil {
		for _, th := range head.findAll(func(x *node) bool { return x.tag == "th" }) {
			out.Columns = append(out.Columns, &screensv1.PageColumn{Label: th.text(), Numeric: th.has("text-right")})
		}
	}
	body := table.find(func(x *node) bool { return x.tag == "tbody" })
	if body == nil {
		body = table
	}
	for _, tr := range body.findAll(func(x *node) bool { return x.tag == "tr" }) {
		if head != nil && inside(tr, head) {
			continue
		}
		row := &screensv1.PageRow{}
		for _, c := range tr.elements() {
			if c.tag == "td" || c.tag == "th" {
				row.Cells = append(row.Cells, readCell(c))
			}
		}
		out.Rows = append(out.Rows, row)
	}
	return out
}

func readCell(c *node) *screensv1.PageCell {
	text := c.text()
	cell := &screensv1.PageCell{Text: text, Href: hrefOf(c)}
	if strong := c.find(func(x *node) bool { return x.tag == "strong" || x.tag == "b" }); strong != nil && strong.text() == text {
		cell.Strong = true
	}
	return cell
}

func hrefOf(n *node) string {
	if n == nil {
		return ""
	}
	link := n
	if n.tag != "a" {
		link = n.find(func(x *node) bool { return x.tag == "a" })
	}
	if link == nil {
		return ""
	}
	return link.get("href")
}

// ── Panels (page_blocks._panel, _panel_items, _paired) ──────────────────────

var headings = map[string]bool{"h2": true, "h3": true, "h4": true, "h5": true, "summary": true}

func readPanel(n *node) *screensv1.PagePanel {
	title := n.find(func(x *node) bool { return x.tag == "h2" || x.tag == "h3" })
	var header *node
	if title != nil {
		header = title
		if title.parent != n {
			header = title.parent
		}
	}
	p := &screensv1.PagePanel{}
	if title != nil {
		p.Title = title.text()
	}
	if header != nil && header != title {
		if sub := header.find(func(x *node) bool { return x.tag == "p" }); sub != nil {
			p.Subtitle = sub.text()
		}
	}
	skip := map[*node]bool{}
	if header != nil {
		skip[header] = true
	}
	p.Items = paired(panelItems(n, skip, nil))
	return p
}

func textItem(text, tone string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: text}, Tone: tone}
}

func toneOf(n *node) string {
	toned := n
	if n.get("data-tone") == "" && n.get("data-edify-tone") == "" {
		toned = n.find(func(x *node) bool { return x.get("data-tone") != "" || x.get("data-edify-tone") != "" })
	}
	if toned == nil {
		return ""
	}
	if t := toned.get("data-edify-tone"); t != "" {
		return t
	}
	return toned.get("data-tone")
}

func isLink(n *node) bool {
	if n.tag == "a" {
		return n.get("href") != "" || n.get("hx-get") != ""
	}
	return n.tag == "button" && n.get("hx-get") != ""
}

func linkItem(n *node) *screensv1.PageLink {
	lines := []string{}
	for _, c := range n.elements() {
		if t := c.text(); t != "" && !c.has("sr-only") {
			lines = append(lines, t)
		}
	}
	href := n.get("hx-get")
	if href == "" {
		href = n.get("href")
	}
	link := &screensv1.PageLink{Text: n.text(), Href: href, Drawer: n.get("hx-target") == "#drawer-container"}
	if len(lines) > 1 {
		link.Text = lines[0]
		link.Caption = strings.Join(lines[1:], " · ")
	}
	return link
}

func listLink(item *node) *screensv1.PageLink {
	caption := item.find(func(x *node) bool { return x.has("block") || x.has("edify-text-caption") })
	link := item.find(func(x *node) bool { return x.tag == "a" })
	out := &screensv1.PageLink{}
	if link != nil {
		out.Text = link.text()
		out.Href = link.get("href")
	} else {
		text := item.text()
		if caption != nil {
			text = strings.TrimSuffix(text, caption.text())
		}
		out.Text = strings.TrimSpace(text)
	}
	if caption != nil && caption != link {
		out.Caption = caption.text()
	}
	return out
}

func panelItems(n *node, skip map[*node]bool, out []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	for _, child := range n.elements() {
		if skip[child] || silent[child.tag] || child.has("sr-only") {
			continue
		}
		switch {
		case headings[child.tag] || child.has("edify-section__heading"):
			out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: child.text()}})
		case child.tag == "ul" || child.tag == "ol":
			links := &screensv1.PageLinks{}
			for _, item := range child.elements() {
				if item.tag == "li" {
					links.Links = append(links.Links, listLink(item))
				}
			}
			out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: links}})
		case child.has("edify-empty-state"):
			out = append(out, textItem(emptyMessage(child), ""))
		case child.tag == "p" || (child.tag == "span" && toneOf(child) != ""):
			if text := child.text(); text != "" {
				out = append(out, textItem(text, toneOf(child)))
			}
		case isLink(child):
			link := linkItem(child)
			if link.Text != "" {
				if len(out) > 0 && out[len(out)-1].GetLinks() != nil {
					last := out[len(out)-1].GetLinks()
					last.Links = append(last.Links, link)
				} else {
					out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{link}}}})
				}
			}
		case child.tag == "form" || child.tag == "select" || child.tag == "input" || child.tag == "textarea" || child.tag == "template":
		case len(child.elements()) == 0:
			if text := child.text(); text != "" {
				out = append(out, textItem(text, ""))
			}
		default:
			out = panelItems(child, skip, out)
		}
	}
	return out
}

// figure is page_blocks.FIGURE: a figure on its own.
var figure = regexp.MustCompile(`^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$`)

var pagerCaption = regexp.MustCompile(`^Showing\s+\d`)

func plainText(item *screensv1.PagePanelItem) (string, bool) {
	t, ok := item.Kind.(*screensv1.PagePanelItem_Text)
	if !ok {
		return "", false
	}
	return t.Text, true
}

func paired(items []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	out := []*screensv1.PagePanelItem{}
	for i := 0; i < len(items); {
		label, isText := plainText(items[i])
		var value string
		pair := false
		if isText && i+1 < len(items) && !pagerCaption.MatchString(label) && strings.IndexFunc(label, unicode.IsLetter) >= 0 {
			if v, ok := plainText(items[i+1]); ok && figure.MatchString(strings.TrimSpace(v)) {
				value, pair = strings.TrimSpace(v), true
			}
		}
		if !pair {
			out = append(out, items[i])
			i++
			continue
		}
		row := &screensv1.PageDataRow{Label: label, Value: value, Tone: items[i+1].Tone}
		if len(out) > 0 && out[len(out)-1].GetRows() != nil {
			rows := out[len(out)-1].GetRows()
			rows.Rows = append(rows.Rows, row)
		} else {
			out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{row}}}})
		}
		i += 2
	}
	return out
}

// ── My Performance's indicator cards (css_charts) ───────────────────────────

var barTitle = regexp.MustCompile(`^([^:]+):\s*(-?[\d,]*\.?\d+)\s*$`)

func chartOf(holder *node) *screensv1.PageChart {
	chart := holder.find(func(x *node) bool { return x.has("tp-chart") })
	if chart == nil {
		return nil
	}
	categories := []string{}
	names := []string{}
	series := map[string][]float64{}
	for _, group := range chart.findAll(func(x *node) bool { return x.has("tp-chart__group") }) {
		name := group.get("data-tp-bar")
		if name == "" {
			continue
		}
		categories = append(categories, name)
		for _, bar := range group.findAll(func(x *node) bool { return x.has("tp-chart__bar") }) {
			m := barTitle.FindStringSubmatch(strings.TrimPrefix(bar.get("title"), name+" "))
			if m == nil {
				continue
			}
			label := pyCapitalize(strings.TrimSpace(m[1]))
			values, ok := series[label]
			if !ok {
				values = make([]float64, len(categories)-1)
				names = append(names, label)
			}
			v, _ := strconv.ParseFloat(strings.ReplaceAll(m[2], ",", ""), 64)
			series[label] = append(values, v)
		}
		for _, label := range names {
			for len(series[label]) < len(categories) {
				series[label] = append(series[label], 0)
			}
		}
	}
	if len(categories) == 0 || len(names) == 0 {
		return nil
	}
	out := &screensv1.PageChart{Horizontal: true, Categories: categories}
	for _, label := range names {
		out.Series = append(out.Series, &screensv1.PageSeries{Name: label, Values: series[label]})
	}
	return out
}

func pyCapitalize(s string) string {
	if s == "" {
		return s
	}
	r := []rune(strings.ToLower(s))
	r[0] = unicode.ToUpper(r[0])
	return string(r)
}

func chartsIn(card *node) []*node {
	out := []*node{}
	for _, holder := range card.findAll(func(x *node) bool { _, ok := x.attrs["data-tp-chart"]; return ok }) {
		if chartOf(holder) != nil {
			out = append(out, holder)
		}
	}
	return out
}

// areaCard is css_charts.is_area_card and read_area: the card's charts,
// each followed by its table; nil when the node is no such card.
func areaCard(n *node) []*screensv1.PageBlock {
	_, isHolder := n.attrs["data-tp-chart"]
	var holders []*node
	switch {
	case n.has("tp-card"):
		holders = chartsIn(n)
		if len(holders) == 0 {
			return nil
		}
	case isHolder && chartOf(n) != nil:
		holders = []*node{n}
	default:
		return nil
	}
	head := n.find(func(x *node) bool { return x.has("tp-card__head") })
	var heading, meta *node
	if head != nil {
		heading = head.find(func(x *node) bool { return x.tag == "h2" })
		meta = head.find(func(x *node) bool { return x.has("tp-card__meta") })
	}
	out := []*screensv1.PageBlock{}
	for _, holder := range holders {
		caption := holder.find(func(x *node) bool { return x.has("tp-chart-title") })
		chart := chartOf(holder)
		switch {
		case heading != nil && len(holders) == 1:
			chart.Title = heading.text()
		case caption != nil:
			chart.Title = caption.text()
		}
		if meta != nil {
			chart.Subtitle = meta.text()
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: chart}})
		for _, table := range holder.findAll(func(x *node) bool { return x.tag == "table" }) {
			out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: readTable(table)}})
		}
	}
	return out
}
