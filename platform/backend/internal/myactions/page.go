package myactions

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// pageParam is the queue's own page ({% paginate rows "table_rows_page" %}).
const pageParam = "table_rows_page"

// zone is settings.TIME_ZONE: date.today() is its day.
var zone = mustZone("Africa/Nairobi")

func mustZone(name string) *time.Location {
	z, err := time.LoadLocation(name)
	if err != nil {
		panic("myactions: " + err.Error())
	}
	return z
}

// view is everything the page is drawn from.
type view struct {
	side   side
	role   Role
	counts counts
	rows   []action
	query  url.Values
	// today is the local day, at midnight UTC as dates are read.
	today time.Time
}

func collapse(text string) string { return closedschools.Collapse(text) }

func or(text, fallback string) string {
	if text == "" {
		return fallback
	}
	return text
}

func textItem(text string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: text}}
}

func panel(items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}}
}

func pluralize(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// provenance is the line over the queue once anything has closed: how many
// the record confirmed.
func provenance(c counts) *screensv1.PageBlock {
	line := fmt.Sprintf("%d of %d resolved action%s confirmed by the record", c.AutoResolved, c.Resolved, pluralize(c.Resolved))
	if c.AutoResolved < c.Resolved {
		line += "; the rest were closed manually"
	}
	return panel(textItem(line + "."))
}

// tabLinks is the tab bar as the feed reads it: a line of links, each with
// its count.
func tabLinks(c counts) *screensv1.PagePanelItem {
	links := &screensv1.PageLinks{}
	for _, tab := range rules.Tabs {
		n := c.Total
		switch tab[0] {
		case "open":
			n = c.Open
		case "overdue":
			n = c.Overdue
		case "resolved":
			n = c.Resolved
		}
		links.Links = append(links.Links, &screensv1.PageLink{Text: collapse(tab[1] + " " + strconv.Itoa(n)), Href: "?tab=" + tab[0]})
	}
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: links}}
}

// stateLabel is _STATE_TONE's label, or the state in title case.
func stateLabel(state string) string {
	if pair, ok := rules.StateTones[state]; ok {
		return pair[0]
	}
	return pyTitle(state)
}

// issueLabel is ISSUE_LABELS, or the issue made readable.
func issueLabel(issue string) string {
	if label, ok := rules.IssueLabels[issue]; ok {
		return label
	}
	readable := strings.ReplaceAll(issue, "_", " ")
	for i, r := range readable {
		return strings.ToTitle(string(r)) + strings.ToLower(readable[i+len(string(r)):])
	}
	return readable
}

// stateCell is the state's pill and the lines under it: who closed a
// resolved action, and why one came back. The pill alone is read as a pill.
func stateCell(a action) *screensv1.PageCell {
	label := collapse(stateLabel(a.State))
	parts := []string{stateLabel(a.State)}
	if a.State == rules.ResolvedState {
		if a.ResolvedBySystem {
			parts = append(parts, "Confirmed by the record")
		} else {
			parts = append(parts, "Closed manually")
		}
	}
	if a.ReturnedReason != "" {
		parts = append(parts, a.ReturnedReason)
	}
	text := collapse(strings.Join(parts, " "))
	if text == label {
		return &screensv1.PageCell{Text: text, Tone: "primary", Badge: true}
	}
	return &screensv1.PageCell{Text: text}
}

// due is the due day and, for active work past it, how late it is.
func due(a action, today time.Time) string {
	if a.DueDate == nil {
		return "—"
	}
	text := a.DueDate.Format("2 Jan")
	if a.DueDate.Before(today) && active(a.State) {
		late := int(today.Sub(*a.DueDate).Hours() / 24)
		text += fmt.Sprintf(" %d day%s late", late, pluralize(late))
	}
	return text
}

// actionCell is the row's way on. Active work opens its route: from the
// Actions menu where the row has a second step (Acknowledge for the
// recipient, Escalate for the sender of overdue work; neither reaches the
// app), else as the row's own link. A blank route opens nothing. Closed work
// views the school.
func actionCell(a action, sender bool) *screensv1.PageCell {
	c := &screensv1.PageCell{}
	switch {
	case !active(a.State):
		c.Actions = []*screensv1.PageAction{{Key: "button", Label: "View school", Primary: true, Enabled: true, Href: "/schools/" + a.SchoolPK}}
	case a.Route == "":
	case !sender || a.State == rules.OverdueState:
		c.Actions = []*screensv1.PageAction{{Key: "menu", Label: "Open", Enabled: true, Href: a.Route}}
	default:
		c.Actions = []*screensv1.PageAction{{Key: "button", Label: "Open", Primary: true, Enabled: true, Href: a.Route}}
	}
	return c
}

// row is one action as the table writes it. The School ID is filled in by
// the page's script, so the feed reads none.
func row(a action, today time.Time, sender bool) *screensv1.PageRow {
	id := "—"
	if a.SchoolPK != "" {
		id = ""
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: id},
		{Text: collapse(or(a.School, "School") + " " + or(a.District, "—")), Href: "/schools/" + a.SchoolPK},
		{Text: collapse(a.RequestedAction + " " + issueLabel(a.IssueType))},
		{Text: collapse(or(a.Counterparty, "—"))},
		{Text: collapse(due(a, today))},
		stateCell(a),
		actionCell(a, sender),
	}}
}

// columns are the table's headings around the other party's.
func columns(counterparty string) []string {
	return []string{"School ID", "School", "Requested action", counterparty, "Due", "State", "Action"}
}

// page is the whole answer.
func page(v view) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if s := v.role.Strip; s != nil {
		tabs := &screensv1.PageLinkTabs{Label: s.Label, Scrolls: s.Scrolls}
		for _, t := range s.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	if v.counts.Resolved > 0 {
		blocks = append(blocks, provenance(v.counts))
	}
	if len(v.rows) == 0 {
		blocks = append(blocks, panel(tabLinks(v.counts), textItem(v.side.empty)))
		return response(v.side, blocks)
	}
	blocks = append(blocks, panel(tabLinks(v.counts)))
	t := &screensv1.PageTable{}
	headings := columns(v.side.column)
	for i, l := range headings {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: l, Numeric: i == len(headings)-1})
	}
	number, pages := closedschools.PageOf(v.query.Get(pageParam), len(v.rows), rules.PageSize)
	for _, a := range v.rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(v.rows))] {
		t.Rows = append(t.Rows, row(a, v.today, v.side.sender))
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(v.rows), rules.PageSize, v.query, rules.QueryKeysNotPassed))
	}
	return response(v.side, blocks)
}

func response(sd side, blocks []*screensv1.PageBlock) *screensv1.GetPageResponse {
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Urgent Attention",
			Title:       sd.title,
			Description: sd.intro,
		},
		Blocks:  blocks,
		WebPath: sd.path,
	}
}
