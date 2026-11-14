package policycompliance

import (
	"net/url"
	"strconv"
	"time"

	_ "time/tzdata" // the first-opened day is Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// zone is settings.TIME_ZONE: the server's day and the zone |date writes in.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("policycompliance: " + err.Error())
	}
	return z
}()

const pageParam = "rows_page"

func collapse(text string) string { return closedschools.Collapse(text) }

// thousands is a registered count as the registry writes it: 1,234.
func thousands(n int) string {
	s := strconv.Itoa(n)
	out := ""
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			out += ","
		}
		out += string(c)
	}
	return out
}

// humanise is _humanise: seconds as "45s", "3m 20s" or "1h 5m".
func humanise(seconds int) string {
	if seconds <= 0 {
		return "0s"
	}
	minutes, rest := seconds/60, seconds%60
	if minutes < 60 {
		if minutes == 0 {
			return strconv.Itoa(rest) + "s"
		}
		return strconv.Itoa(minutes) + "m " + strconv.Itoa(rest) + "s"
	}
	return strconv.Itoa(minutes/60) + "h " + strconv.Itoa(minutes%60) + "m"
}

// completion is reading_completion_key: read outside the viewer, not
// monitored (no reading time required), completed, not read or partial.
func completion(a ack) string {
	switch {
	case a.Offline:
		return "completed_offline"
	case a.Required <= 0:
		return "not_monitored"
	case a.Active >= a.Required:
		return "completed"
	case a.Active <= 0:
		return "not_read"
	}
	return "partial"
}

func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// filterBar is the page's filter bar: the policy and the status.
func filterBar(f filters, options []option) *screensv1.PageBlock {
	policy := &screensv1.PageFilter{Name: "document", Value: f.Document, Caption: "Policy",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All policies"}}}
	for _, o := range options {
		policy.Options = append(policy.Options, &screensv1.PageFilterOption{Value: o.ID, Label: collapse(o.Title)})
	}
	state := &screensv1.PageFilter{Name: "state", Value: f.State, Caption: "Status", Options: []*screensv1.PageFilterOption{
		{Value: "", Label: "All"}, {Value: "pending", Label: "Pending"}, {Value: "agreed", Label: "Agreed"}, {Value: "disagreed", Label: "Disagreed"},
	}}
	// A filter reads as the option selected: a value none of its options
	// holds selects none.
	for _, f := range []*screensv1.PageFilter{policy, state} {
		chosen := ""
		for _, o := range f.Options {
			if o.Value == f.Value {
				chosen = f.Value
			}
		}
		f.Value = chosen
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{policy, state}}}}
}

// table is the acknowledgements, one page of them, and the shared pager.
func table(r report, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, c := range []string{"User", "Role", "Policy", "Version", "First Opened", "Active Reading Time", "Viewer Completion", "Acknowledgement"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	if len(r.Rows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No acknowledgement records in your scope yet."}}}}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(r.Rows), rules.PageSize)
	for _, a := range r.Rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(r.Rows))] {
		role := a.Role
		if role == "" {
			role = "—"
		}
		cells := []*screensv1.PageCell{}
		for _, v := range []string{
			a.User, role, a.Policy, "v" + strconv.Itoa(a.Version), a.FirstOpened.In(zone).Format("02 Jan"),
			humanise(a.Active) + " of " + humanise(a.Required) + " required",
		} {
			cells = append(cells, &screensv1.PageCell{Text: collapse(v)})
		}
		// The viewer completion is a pill, read as a badge whatever its colour.
		cells = append(cells, &screensv1.PageCell{Text: rules.CompletionLabels[completion(a)], Tone: "primary", Badge: true},
			&screensv1.PageCell{Text: collapse(label(rules.States, a.State))})
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(pageParam, number, pages, len(r.Rows), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return out
}

func page(role Role, r report, f filters, options []option, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "People", Title: "Policy and Manual Compliance", Description: role.ScopeNote}
	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Policy compliance", Metrics: []*screensv1.PageMetric{
		{Label: rules.MetricLabels[acceptedKey], Value: thousands(r.Accepted), Href: rules.MetricDrilldowns[acceptedKey]},
		{Label: rules.MetricLabels[overdueKey], Value: thousands(r.Late), Href: rules.MetricDrilldowns[overdueKey]},
	}}}}
	counts := []*screensv1.PagePanelItem{text("Required " + strconv.Itoa(r.Required)), text("Pending " + strconv.Itoa(r.Pending))}
	if r.Required > len(r.Rows) {
		counts = append(counts, text("Table shows the first 1,000 rows; the figures above count the whole scope."))
	}
	counts = append(counts, text("Declined "+strconv.Itoa(r.Declined)))
	blocks := []*screensv1.PageBlock{strip, panel("", counts...), filterBar(f, options)}
	if role.Strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: role.Strip.Label, Scrolls: role.Strip.Scrolls}
		for _, t := range role.Strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	blocks = append(blocks, table(r, query)...)
	if role.Comments {
		// The queue is empty here: a reader with comments waiting is passed on.
		blocks = append(blocks, panel("Policy Comments",
			text("Private to HR and the Country Director. A line manager sees whether their team answered, never what they wrote."),
			text("No comments awaiting review.")))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}
