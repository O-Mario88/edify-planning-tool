package feeddom

import (
	"regexp"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// Package feeddom writes a page as the templates write it, a tree of
// elements, and reads it into blocks by the rules the existing feed reads
// rendered HTML with (apps.mobile_feed.page_blocks, page_forms, css_charts).
// Shared by the pages Go builds from card templates (Team Performance,
// Partners, …).
//
// The page is written as the templates write it, as a tree of elements
// (templates/pages/team_performance/index.html and its partials), and read
// into blocks by the same rules the existing feed reads the rendered HTML
// with (apps.mobile_feed.page_blocks and css_charts): the part of them this
// page reaches. The shared components (the filter bar, the section tabs and
// the KPI strips) are drawn as their blocks directly.

// node is one element of the page, or (pre) a component already read.
type Node struct {
	tag      string
	classes  map[string]bool
	attrs    map[string]string
	children []any // string or *Node
	parent   *Node
	pre      *screensv1.PageBlock
	// Later is the part a lazy section loads (hx-get with a Later trigger):
	// built when the walker reaches it, nil when that request is not found.
	Later func() *Node
}

func El(tag, class string, children ...any) *Node {
	n := &Node{tag: tag, classes: map[string]bool{}, attrs: map[string]string{}}
	for _, c := range strings.Fields(class) {
		n.classes[c] = true
	}
	n.Add(children...)
	return n
}

// attr sets attributes: attr("href", "?x", "title", "t").
func (n *Node) Attr(kv ...string) *Node {
	for i := 0; i+1 < len(kv); i += 2 {
		n.attrs[kv[i]] = kv[i+1]
	}
	return n
}

func (n *Node) Add(children ...any) *Node {
	for _, c := range children {
		switch v := c.(type) {
		case nil:
		case string:
			if v != "" {
				n.children = append(n.children, v)
			}
		case *Node:
			if v != nil {
				v.parent = n
				n.children = append(n.children, v)
			}
		case []*Node:
			for _, x := range v {
				n.Add(x)
			}
		case []any:
			n.Add(v...)
		default:
			panic("teamperformance: node child")
		}
	}
	return n
}

func PreBlock(b *screensv1.PageBlock) *Node {
	n := El("div", "")
	n.pre = b
	return n
}

func (n *Node) has(class string) bool { return n.classes[class] }

func (n *Node) Get(name string) string { return n.attrs[name] }

func (n *Node) nodes() []*Node {
	out := []*Node{}
	var visit func(*Node)
	visit = func(x *Node) {
		for _, c := range x.children {
			if child, ok := c.(*Node); ok {
				out = append(out, child)
				visit(child)
			}
		}
	}
	visit(n)
	return out
}

func (n *Node) find(test func(*Node) bool) *Node {
	for _, x := range n.nodes() {
		if test(x) {
			return x
		}
	}
	return nil
}

func (n *Node) findAll(test func(*Node) bool) []*Node {
	out := []*Node{}
	for _, x := range n.nodes() {
		if test(x) {
			out = append(out, x)
		}
	}
	return out
}

func (n *Node) elements() []*Node {
	out := []*Node{}
	for _, c := range n.children {
		if child, ok := c.(*Node); ok {
			out = append(out, child)
		}
	}
	return out
}

var silent = map[string]bool{"script": true, "style": true, "svg": true, "noscript": true, "template": true}

// text is Node.text: the element's text, whitespace collapsed, what only a
// screen reader hears left out.
func (n *Node) text() string { return n.textOf(true) }

// partJoiner is page_blocks._PART_JOINER: what joins two parts the page
// draws apart with nothing between them.
const partJoiner = " · "

// joiner gathers words as Node.text reads them: at an element's edge, where
// the words so far end in a lower-case letter and the next start with a
// capital, it puts partJoiner between them (page_blocks._sentence_edges).
type joiner struct {
	b    strings.Builder
	edge bool
}

func (j *joiner) write(s string) {
	if s == "" {
		j.edge = false
		return
	}
	if j.edge && j.b.Len() > 0 {
		last, _ := utf8.DecodeLastRuneInString(j.b.String())
		first, _ := utf8.DecodeRuneInString(s)
		if unicode.IsLower(last) && unicode.IsUpper(first) {
			j.b.WriteString(partJoiner)
		}
	}
	j.b.WriteString(s)
	j.edge = false
}

// JoinParts is the text of parts a page draws as elements side by side, as
// Node.text reads them: "Cluster Meetings", "UGX 291K" read
// "Cluster Meetings · UGX 291K"; "Unit", "schools" read "Unitschools".
func JoinParts(parts ...string) string {
	var j joiner
	for _, p := range parts {
		j.edge = true
		j.write(p)
	}
	return j.b.String()
}

// textOf is Node.text: the element's words, whitespace collapsed, what only
// a screen reader hears left out when shown, parts drawn apart read apart
// (joiner): "Cluster Meetings · UGX 291K".
func (n *Node) textOf(shown bool) string { return n.reading(shown, true) }

// wordsText is Node.text(apart=False): the reading without partJoiner, for
// the rules that count a part's words to decide what kind of part it is
// (fallback), so they decide as they always have.
func (n *Node) wordsText() string { return n.reading(true, false) }

func (n *Node) reading(shown, apart bool) string {
	var j joiner
	var collect func(*Node)
	collect = func(x *Node) {
		for _, c := range x.children {
			switch v := c.(type) {
			case string:
				j.write(v)
			case *Node:
				if silent[v.tag] || (shown && v.has("sr-only")) {
					continue
				}
				j.edge = apart
				collect(v)
				j.edge = apart
			}
		}
	}
	collect(n)
	return strings.Join(strings.Fields(j.b.String()), " ")
}

// collect is Node._collect(parts, shown=True): the element's words as
// written, what only a screen reader hears left out.
func (n *Node) collect(b *strings.Builder) {
	for _, c := range n.children {
		switch v := c.(type) {
		case string:
			b.WriteString(v)
		case *Node:
			if !silent[v.tag] && !v.has("sr-only") {
				v.collect(b)
			}
		}
	}
}

// Text is the element's text as the feed reads it (Node.text).
func (n *Node) Text() string { return n.text() }

// introLimit is page_forms.INTRO_LIMIT: the characters a card may show
// around its one form and still be read as that form.
const introLimit = 400

// controls are drawer_blocks.CONTROLS, and notFields the inputs among them
// that are not fields the person fills (NOT_FIELDS).
var (
	controls  = map[string]bool{"input": true, "select": true, "textarea": true}
	notFields = map[string]bool{"hidden": true, "submit": true, "button": true, "reset": true, "image": true}
)

// isPostForm is page_forms.is_post_form: a form that posts and holds a
// field the person fills.
func isPostForm(n *Node) bool {
	return n.tag == "form" && strings.EqualFold(n.Get("method"), "post") && n.find(func(x *Node) bool {
		return controls[x.tag] && (x.tag != "input" || !notFields[strings.ToLower(x.Get("type"))])
	}) != nil
}

// CardForm is page_forms._form_of for a card (an edify-surface or card
// element): its one POST form when the card shows no more than the intro
// limit around it and no table or list outside it, else nil (the card is
// read as a panel, its forms skipped).
func CardForm(card *Node) *Node {
	if !card.has("edify-surface") && !card.has("card") {
		return nil
	}
	forms := card.findAll(func(x *Node) bool { return x.tag == "form" })
	if len(forms) != 1 || !isPostForm(forms[0]) {
		return nil
	}
	form := forms[0]
	if utf8.RuneCountInString(card.text())-utf8.RuneCountInString(form.text()) > introLimit {
		return nil
	}
	if card.find(func(x *Node) bool {
		return (x.tag == "table" || x.tag == "ul" || x.tag == "ol" || x.tag == "dl") && !inside(x, form)
	}) != nil {
		return nil
	}
	return form
}

// Outside is page_forms._outside: the card's first element outside its form
// that passes test, or nil.
func Outside(card, form *Node, test func(*Node) bool) *Node {
	return card.find(func(x *Node) bool { return test(x) && !inside(x, form) })
}

// Tag is the element's tag.
func (n *Node) Tag() string { return n.tag }

// FindAll is every element under n, in document order, that passes test.
func (n *Node) FindAll(test func(*Node) bool) []*Node { return n.findAll(test) }

// Written is drawer_blocks._value's textarea value: the element's own
// words as written, stripped at the ends, not collapsed.
func (n *Node) Written() string {
	var b strings.Builder
	for _, c := range n.children {
		if t, ok := c.(string); ok {
			b.WriteString(t)
		}
	}
	return strings.TrimSpace(b.String())
}

// Has is whether the element carries the class.
func (n *Node) Has(class string) bool { return n.has(class) }

func inside(x, ancestor *Node) bool {
	for ; x != nil; x = x.parent {
		if x == ancestor {
			return true
		}
	}
	return false
}

// ── The walk (page_blocks._blocks) ──────────────────────────────────────────

func Walk(n *Node, out []*screensv1.PageBlock) []*screensv1.PageBlock {
	for _, child := range n.elements() {
		if silent[child.tag] {
			continue
		}
		if child.pre != nil {
			out = append(out, child.pre)
			continue
		}
		if child.Later != nil {
			if part := child.Later(); part != nil {
				out = Walk(part, out)
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
			out = Walk(child, out)
		} else if b := fallback(child); b != nil {
			out = append(out, b)
		}
	}
	return out
}

func blockOf(n *Node) *screensv1.PageBlock {
	if n.tag == "dl" && n.find(func(x *Node) bool { return x.tag == "dt" }) != nil {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Facts{Facts: readFacts(n)}}
	}
	if surface(n) && !holdsBlocks(n) && n.find(func(x *Node) bool { return x.Later != nil }) == nil && n.text() != "" {
		if p := ReadPanel(n); len(p.Items) > 0 || p.Title != "" {
			return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
		}
	}
	if n.tag == "table" {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: readTable(n)}}
	}
	if n.has("edify-empty-state") {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyMessage(n)}}
	}
	return nil
}

func holdsBlocks(n *Node) bool {
	return n.find(func(x *Node) bool { return x.pre != nil || x.tag == "table" || surface(x) }) != nil
}

// surface is a card the page draws as a surface of its own
// (edify-surface rounded-surface): read as a panel, never inside another.
func surface(n *Node) bool { return n.has("edify-surface") && n.has("rounded-surface") }

// readFacts is page_blocks._facts: each term with the first value beside it
// and that value's link.
func readFacts(dl *Node) *screensv1.PageFacts {
	out := &screensv1.PageFacts{}
	for _, term := range dl.findAll(func(x *Node) bool { return x.tag == "dt" }) {
		var value *Node
		if term.parent != nil {
			value = term.parent.find(func(x *Node) bool { return x.tag == "dd" })
		}
		f := &screensv1.PageFact{Label: term.text(), Href: hrefOf(value)}
		if value != nil {
			f.Value = value.text()
		}
		out.Facts = append(out.Facts, f)
	}
	return out
}

func holdsKnown(n *Node) bool {
	return n.find(func(x *Node) bool {
		_, tablist := x.attrs["data-edify-tablist"]
		return tablist || x.has("edify-empty-state") || x.Later != nil || x.pre != nil
	}) != nil
}

func fallback(n *Node) *screensv1.PageBlock {
	if n.tag == "form" || n.tag == "dialog" || n.tag == "template" {
		return nil
	}
	text := n.text()
	if (n.tag == "h2" || n.tag == "h3") && strings.IndexFunc(text, unicode.IsLetter) >= 0 {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: text}}
	}
	if len(strings.Fields(n.wordsText())) < 2 {
		return nil
	}
	p := ReadPanel(n)
	if len(p.Items) == 0 && p.Title == "" {
		p.Items = []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: text}}}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
}

func emptyMessage(n *Node) string {
	empty := n
	if !n.has("edify-empty-state") {
		empty = n.find(func(x *Node) bool { return x.has("edify-empty-state") })
	}
	if empty == nil {
		return ""
	}
	if m := empty.find(func(x *Node) bool { return x.has("edify-empty-state__message") }); m != nil {
		return m.text()
	}
	return empty.text()
}

// ── Tables (page_blocks._table, a bare table) ───────────────────────────────

func readTable(table *Node) *screensv1.PageTable {
	out := &screensv1.PageTable{}
	head := table.find(func(x *Node) bool { return x.tag == "thead" })
	if head != nil {
		for _, th := range head.findAll(func(x *Node) bool { return x.tag == "th" }) {
			out.Columns = append(out.Columns, &screensv1.PageColumn{Label: th.text(), Numeric: th.has("text-right")})
		}
	}
	body := table.find(func(x *Node) bool { return x.tag == "tbody" })
	if body == nil || head == nil && (len(table.findAll(func(x *Node) bool { return x.tag == "tbody" })) > 1 ||
		table.find(func(x *Node) bool { return x.tag == "tfoot" }) != nil) {
		// A table without a head whose groups are its bodies, or with a
		// footer, is read whole.
		body = table
	}
	for _, tr := range body.findAll(func(x *Node) bool { return x.tag == "tr" }) {
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

func readCell(c *Node) *screensv1.PageCell {
	text := c.text()
	cell := &screensv1.PageCell{Text: text, Href: hrefOf(c)}
	if strong := c.find(func(x *Node) bool { return x.tag == "strong" || x.tag == "b" }); strong != nil && strong.text() == text {
		cell.Strong = true
	}
	return cell
}

func hrefOf(n *Node) string {
	if n == nil {
		return ""
	}
	link := n
	if n.tag != "a" {
		link = n.find(func(x *Node) bool { return x.tag == "a" })
	}
	if link == nil {
		return ""
	}
	return link.Get("href")
}

// ── Panels (page_blocks._panel, _panel_items, _paired) ──────────────────────

var headings = map[string]bool{"h2": true, "h3": true, "h4": true, "h5": true, "summary": true}

func ReadPanel(n *Node) *screensv1.PagePanel {
	title := n.find(func(x *Node) bool { return x.tag == "h2" || x.tag == "h3" })
	var header *Node
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
		if sub := header.find(func(x *Node) bool { return x.tag == "p" }); sub != nil {
			p.Subtitle = sub.text()
		}
	}
	if header != nil && header != title {
		for _, pill := range header.findAll(func(x *Node) bool { return x.tag == "span" && x.has("rounded-pill") }) {
			p.Badges = append(p.Badges, &screensv1.PageBadge{Text: pill.text(), Tone: badgeTone(pill), Title: pill.Get("title")})
		}
	}
	skip := map[*Node]bool{}
	if header != nil {
		skip[header] = true
	}
	p.Items = paired(PanelItems(n, skip, nil))
	return p
}

// badgeTones is page_blocks.BADGE_TONES: a pill's tone by its background.
var badgeTones = [][2]string{
	{"bg-emerald", "good"}, {"bg-amber", "caution"}, {"bg-rose", "alert"},
	{"bg-red", "alert"}, {"bg-sky", "info"}, {"bg-blue", "info"},
}

// badgeTone is page_blocks._badge_tone: the first marker any of the pill's
// classes holds, else plain.
func badgeTone(pill *Node) string {
	for _, marker := range badgeTones {
		for class := range pill.classes {
			if strings.Contains(class, marker[0]) {
				return marker[1]
			}
		}
	}
	return "plain"
}

func textItem(text, tone string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: text}, Tone: tone}
}

func toneOf(n *Node) string {
	toned := n
	if n.Get("data-tone") == "" && n.Get("data-edify-tone") == "" {
		toned = n.find(func(x *Node) bool { return x.Get("data-tone") != "" || x.Get("data-edify-tone") != "" })
	}
	if toned == nil {
		return ""
	}
	if t := toned.Get("data-edify-tone"); t != "" {
		return t
	}
	return toned.Get("data-tone")
}

func isLink(n *Node) bool {
	if n.tag == "a" {
		return n.Get("href") != "" || n.Get("hx-get") != ""
	}
	return n.tag == "button" && n.Get("hx-get") != ""
}

func linkItem(n *Node) *screensv1.PageLink {
	lines := []string{}
	for _, c := range n.elements() {
		if t := c.text(); t != "" && !c.has("sr-only") {
			lines = append(lines, t)
		}
	}
	href := n.Get("hx-get")
	if href == "" {
		href = n.Get("href")
	}
	link := &screensv1.PageLink{Text: n.text(), Href: href, Drawer: n.Get("hx-target") == "#drawer-container"}
	if len(lines) > 1 {
		link.Text = lines[0]
		link.Caption = strings.Join(lines[1:], " · ")
	}
	return link
}

func listLink(item *Node) *screensv1.PageLink {
	caption := item.find(func(x *Node) bool { return x.has("block") || x.has("edify-text-caption") })
	link := item.find(func(x *Node) bool { return x.tag == "a" })
	out := &screensv1.PageLink{}
	if link != nil {
		out.Text = link.text()
		out.Href = link.Get("href")
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

// inline is page_blocks.INLINE: the elements a sentence runs through;
// anything else starts a part of its own.
var inline = map[string]bool{
	"a": true, "abbr": true, "b": true, "br": true, "button": true, "code": true, "em": true, "i": true, "mark": true,
	"small": true, "span": true, "strong": true, "sub": true, "sup": true, "time": true, "u": true,
}

// mixed is page_blocks._mixed: whether n holds words of its own beside its
// elements ("Enrollment: " before its bold figure).
func mixed(n *Node) bool {
	words, element := false, false
	for _, c := range n.children {
		switch v := c.(type) {
		case string:
			words = words || strings.TrimSpace(v) != ""
		case *Node:
			element = element || (!silent[v.tag] && v.text() != "")
		}
	}
	return words && element
}

// sentences is page_blocks._sentences: a part whose own words run around its
// elements, read whole: each run of words and inline elements one text item
// (its bold opening as the lead, its links at their words), each block
// inside it read in turn.
func sentences(n *Node, skip map[*Node]bool, out []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	var parts strings.Builder
	links := []*screensv1.PageLink{}
	lead := ""
	tone := n.Get("data-edify-tone")
	if tone == "" {
		tone = n.Get("data-tone")
	}
	flush := func() {
		if text := strings.Join(strings.Fields(parts.String()), " "); text != "" {
			item := textItem(text, tone)
			item.Lead = lead
			if len(links) > 0 {
				item.TextLinks = links
			}
			out = append(out, item)
		}
		parts.Reset()
		links = []*screensv1.PageLink{}
		lead = ""
	}
	for _, c := range n.children {
		child, ok := c.(*Node)
		if !ok {
			parts.WriteString(c.(string))
			continue
		}
		if silent[child.tag] || child.has("sr-only") || skip[child] {
			continue
		}
		if !inline[child.tag] {
			flush()
			out = panelParts([]*Node{child}, skip, out)
			continue
		}
		if child.tag == "br" {
			parts.WriteString(" ")
			continue
		}
		if (child.tag == "strong" || child.tag == "b") && strings.TrimSpace(parts.String()) == "" {
			lead = child.text()
		}
		if isLink(child) && child.text() != "" {
			links = append(links, linkItem(child))
		}
		child.collect(&parts)
	}
	flush()
	return out
}

// panelItems is page_blocks._panel_items: a part with words of its own read
// as sentences, any other part element by element.
func PanelItems(n *Node, skip map[*Node]bool, out []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	if mixed(n) {
		return sentences(n, skip, out)
	}
	return panelParts(n.elements(), skip, out)
}

// panelParts is page_blocks._panel_parts.
func panelParts(children []*Node, skip map[*Node]bool, out []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	for _, child := range children {
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
			out = PanelItems(child, skip, out)
		}
	}
	return out
}

// figure is page_blocks.FIGURE: a figure on its own.
var figure = regexp.MustCompile(`^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$`)

var pagerCaption = regexp.MustCompile(`^Showing\s+\d`)

// plainText is an item _paired may pair: a text with at most its tone.
func PlainText(item *screensv1.PagePanelItem) (string, bool) {
	t, ok := item.Kind.(*screensv1.PagePanelItem_Text)
	if !ok || item.Lead != "" || len(item.TextLinks) > 0 {
		return "", false
	}
	return t.Text, true
}

// Paired is _paired for a page that builds its panel's lines itself: a label
// line followed by its figure is a data row, consecutive rows one list.
func Paired(items []*screensv1.PagePanelItem) []*screensv1.PagePanelItem { return paired(items) }

func paired(items []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	out := []*screensv1.PagePanelItem{}
	for i := 0; i < len(items); {
		label, isText := PlainText(items[i])
		var value string
		pair := false
		if isText && i+1 < len(items) && !pagerCaption.MatchString(label) && strings.IndexFunc(label, unicode.IsLetter) >= 0 {
			if v, ok := PlainText(items[i+1]); ok && figure.MatchString(strings.TrimSpace(v)) {
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

func ChartOf(holder *Node) *screensv1.PageChart {
	chart := holder.find(func(x *Node) bool { return x.has("tp-chart") })
	if chart == nil {
		return nil
	}
	categories := []string{}
	names := []string{}
	series := map[string][]float64{}
	for _, group := range chart.findAll(func(x *Node) bool { return x.has("tp-chart__group") }) {
		name := group.Get("data-tp-bar")
		if name == "" {
			continue
		}
		categories = append(categories, name)
		for _, bar := range group.findAll(func(x *Node) bool { return x.has("tp-chart__bar") }) {
			m := barTitle.FindStringSubmatch(strings.TrimPrefix(bar.Get("title"), name+" "))
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

func chartsIn(card *Node) []*Node {
	out := []*Node{}
	for _, holder := range card.findAll(func(x *Node) bool { _, ok := x.attrs["data-tp-chart"]; return ok }) {
		if ChartOf(holder) != nil {
			out = append(out, holder)
		}
	}
	return out
}

// areaCard is css_charts.is_area_card and read_area: the card's charts,
// each followed by its table; nil when the node is no such card.
func areaCard(n *Node) []*screensv1.PageBlock {
	_, isHolder := n.attrs["data-tp-chart"]
	var holders []*Node
	switch {
	case n.has("tp-card"):
		holders = chartsIn(n)
		if len(holders) == 0 {
			return nil
		}
	case isHolder && ChartOf(n) != nil:
		holders = []*Node{n}
	default:
		return nil
	}
	head := n.find(func(x *Node) bool { return x.has("tp-card__head") })
	var heading, meta *Node
	if head != nil {
		heading = head.find(func(x *Node) bool { return x.tag == "h2" })
		meta = head.find(func(x *Node) bool { return x.has("tp-card__meta") })
	}
	out := []*screensv1.PageBlock{}
	for _, holder := range holders {
		caption := holder.find(func(x *Node) bool { return x.has("tp-chart-title") })
		chart := ChartOf(holder)
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
		for _, table := range holder.findAll(func(x *Node) bool { return x.tag == "table" }) {
			out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: readTable(table)}})
		}
	}
	return out
}
