package decisionlog

import (
	"fmt"
	"net/url"
	"strconv"
	"time"

	_ "time/tzdata" // the page's times are Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// pageParam is the table's own page ({% paginate log.rows
// "decision_log_log_rows_page" %}).
const pageParam = "decision_log_log_rows_page"

// zone is settings.TIME_ZONE, the zone |date writes a time in.
var zone = mustZone("Africa/Nairobi")

func mustZone(name string) *time.Location {
	z, err := time.LoadLocation(name)
	if err != nil {
		panic("decisionlog: " + err.Error())
	}
	return z
}

// decision is one audit row the page lists.
type decision struct {
	Action, ActorRole, SubjectID, Reason, Payload string
	Success                                       bool
	At                                            time.Time
}

// view is everything the page is drawn from.
type view struct {
	role Role
	days int
	// group is the group asked for, as given (activeGroup), known or not.
	group string
	query url.Values
	rows  []decision
}

// label is the action's label, or its name made readable.
func label(action string) string {
	if l, ok := rules.Labels[action]; ok {
		return l
	}
	return capitalize(replaceUnderscores(action))
}

func replaceUnderscores(s string) string {
	out := []byte(s)
	for i, c := range out {
		if c == '_' {
			out[i] = ' '
		}
	}
	return string(out)
}

// detail is _detail: the first payload field of the subject keys that holds
// anything, else the decision made, else the subject's id, else a dash.
func detail(d decision) string {
	payload := value{}
	if d.Payload != "" {
		if v, err := decode([]byte(d.Payload)); err == nil {
			payload = v
		}
	}
	for _, key := range rules.DetailKeys {
		if v, ok := payload.get(key); ok && v.truthy() {
			return v.pyStr()
		}
	}
	if v, ok := payload.get("decision"); ok && v.truthy() {
		return capitalize(replaceUnderscores(v.pyStr()))
	}
	if d.SubjectID != "" {
		return d.SubjectID
	}
	return "—"
}

func orDash(text string) string {
	if text == "" {
		return "—"
	}
	return text
}

func cell(text string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: closedschools.Collapse(text)}
}

// row is one decision as the table writes it.
func row(d decision) *screensv1.PageRow {
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		cell(d.At.In(zone).Format("2 Jan, 15:04")),
		cell(label(d.Action) + " " + groupFor(d.Action)),
		cell(detail(d)),
		cell(orDash(d.ActorRole)),
		cell(orDash(d.Reason)),
	}}
}

func textItem(text string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: text}}
}

func panel(items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}}
}

// frame is the decision frame (components/analytics_decision_frame.html) as
// the feed reads it: the confidence's own words sit beside a dot, so the
// feed reads only its label.
func frame() *screensv1.PageBlock {
	return panel(
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: "Data context Selected lookback window"}},
		textItem("Decision frame"),
		textItem("What was decided, by whom, on what record, and with what stated reason?"),
		textItem("Evidence"), textItem("Tamper-evident audit chain"),
		textItem("Freshness"), textItem("Selected lookback window"),
		textItem("Confidence"),
	)
}

func strip(s *Strip) *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Label: s.Label, Scrolls: s.Scrolls}
	for _, t := range s.Tabs {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

// filters is the lookback select; a window it does not offer selects none,
// which the feed reads as the first. The group asked for travels hidden.
func filters(v view) *screensv1.PageBlock {
	f := &screensv1.PageFilter{Name: "days", Label: "Period", Value: strconv.Itoa(rules.DayOptions[0])}
	for _, option := range rules.DayOptions {
		value := strconv.Itoa(option)
		if option == v.days {
			f.Value = value
		}
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: value, Label: "Last " + value + " days"})
	}
	out := &screensv1.PageFilters{Filters: []*screensv1.PageFilter{f}}
	if v.group != "" {
		out.Hidden = map[string]string{"group": v.group}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: out}}
}

// groupTabs is the tab rail of groups: All, then each group, the one asked
// for current (none, for a group that is not one).
func groupTabs(v view) *screensv1.PageBlock {
	days := strconv.Itoa(v.days)
	tabs := []*screensv1.PageLinkTab{{Label: "All", Href: "?days=" + days, Active: v.group == ""}}
	for _, g := range rules.Groups {
		tabs = append(tabs, &screensv1.PageLinkTab{
			Label: g.Name, Href: "?group=" + g.Name + "&days=" + days, Active: v.group == g.Name,
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}}
}

var columns = []string{"When", "Decision", "Subject", "By", "Reason given"}

// table is one page of the decisions and, past one page, the pager under
// it, which the feed reads as a panel of its own.
func table(v view) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, l := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: l})
	}
	number, pages := closedschools.PageOf(v.query.Get(pageParam), len(v.rows), rules.PageSize)
	for _, d := range v.rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(v.rows))] {
		t.Rows = append(t.Rows, row(d))
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(pageParam, number, pages, len(v.rows), rules.PageSize, v.query, rules.QueryKeysNotPassed))
	}
	return out
}

// page is the whole answer, in the order the feed reads the workspace: the
// document title the scope carries, the strip, the decision frame, the
// panel's own filters, groups, table and footnote, and the workspace's
// closing line.
func page(v view) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{panel(textItem("Decision Log · Edify"))}
	if v.role.Strip != nil {
		blocks = append(blocks, strip(v.role.Strip))
	}
	blocks = append(blocks, frame(), filters(v), groupTabs(v))
	if len(v.rows) > 0 {
		blocks = append(blocks, table(v)...)
	} else {
		blocks = append(blocks, panel(textItem("No decisions recorded in this period"), textItem("Widen the window or clear the filter.")))
	}
	blocks = append(blocks,
		panel(textItem(fmt.Sprintf("Every row is part of a hash chain — an entry cannot be altered or removed without breaking the chain. "+
			"Showing the %d most recent decisions in scope. Scope: %s · last %d days.", len(v.rows), v.role.ScopeLabel, v.days))),
		panel(textItem("All data is provisional and subject to verification.")),
	)
	return &screensv1.GetPageResponse{Header: &screensv1.PageHeader{Title: "Decision Log"}, Blocks: blocks, WebPath: Path}
}
