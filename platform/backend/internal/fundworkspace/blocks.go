// Package fundworkspace draws partials/finance/fund_workspace.html as the
// existing feed reads it: the shared frame of the people who move money,
// the Accountant's Disbursements and the Program Lead's Fund Approvals.
// The pages compute their own figures; this draws them the one way.
package fundworkspace

import (
	"fmt"
	"sort"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Strip is components/context_metrics.html over the page's figures: a
// helper that is a sentence rather than a figure is read as the figure's
// note (professional_kpis' brief_helper).
func Strip(title string, labels, values, helpers []string) *screensv1.PageBlock {
	s := &screensv1.PageStrip{Title: title}
	for i, label := range labels {
		m := &screensv1.PageMetric{Label: label, Value: values[i], Helper: helpers[i]}
		if brief := schoolprofile.BriefHelper(helpers[i]); brief != helpers[i] {
			m.Helper, m.Note = brief, helpers[i]
		}
		s.Metrics = append(s.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: s}}
}

// Queue is the requesters' strip: its title and count, then each requester
// as a link to their detail; with nobody to show, the queue's empty words.
func Queue(title string, links []*screensv1.PageLink, emptyTitle, emptyText string) []*screensv1.PageBlock {
	if len(links) == 0 {
		return []*screensv1.PageBlock{Panel("", Text(emptyTitle), Text(emptyText))}
	}
	return []*screensv1.PageBlock{
		Panel("", Text(fmt.Sprintf("%s %d", title, len(links)))),
		Panel("", Links(links...)),
	}
}

// Progress is the side panel's progress section.
type Progress struct {
	Title, Status, Allocation, Caption, Approved string
	Pct                                          int64
	Link, LinkLabel                              string
}

// Rate is the side panel's rate section: the three counts, its title, the
// donut's subline and the words for a month with no decisions.
type Rate struct {
	Title, Subline, Empty       string
	Approved, Returned, Pending int64
}

// Side is the side panel as the feed reads it: the progress section, then
// the rate (the month's rows above them are not read).
func Side(title string, p Progress, r Rate) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{
		Heading(p.Title),
		Text(p.Status),
		{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
			{Label: "Total Allocation", Value: p.Allocation}}}}},
		Text(p.Caption),
		Text(fmt.Sprintf("%s (%d%%)", p.Approved, min(p.Pct, 100))),
		Links(&screensv1.PageLink{Text: p.LinkLabel, Href: p.Link}),
		Heading(r.Title),
	}
	total := r.Approved + r.Returned + r.Pending
	if total == 0 {
		return Panel(title, append(items, Text(r.Empty))...)
	}
	rows := &screensv1.PageDataRows{}
	legend := []*screensv1.PageLink{}
	for _, part := range []struct {
		label string
		n     int64
	}{{"Approved", r.Approved}, {"Returned", r.Returned}, {"Pending", r.Pending}} {
		v := fmt.Sprintf("%d%%", budgetpage.Percentage(part.n, total))
		rows.Rows = append(rows.Rows, &screensv1.PageDataRow{Label: part.label, Value: v})
		legend = append(legend, &screensv1.PageLink{Text: part.label + v})
	}
	return Panel(title, append(items,
		Text(fmt.Sprintf("%d%% · %s", budgetpage.Percentage(r.Approved, total), r.Subline)),
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: rows}}, Links(legend...))...)
}

// Mix is fund_workspace.budget_mix drawn: the five largest labels (the rest
// folded into Other), each share's figure when it is 7% or more, then the
// legend; the card's empty state, read as an empty table, when nothing is
// costed. labels is the order the page first met each label.
func Mix(title, currency string, labels []string, totals map[string]int64) *screensv1.PageBlock {
	type share struct {
		label string
		total int64
	}
	ordered := []share{}
	for _, l := range labels {
		if totals[l] != 0 {
			ordered = append(ordered, share{l, totals[l]})
		}
	}
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].total > ordered[j].total })
	if len(ordered) > 5 {
		var rest int64
		for _, s := range ordered[5:] {
			rest += s.total
		}
		ordered = append(ordered[:5:5], share{"Other", rest})
	}
	if len(ordered) == 0 {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: title, EmptyMessage: "No costed activities this monthThe budget mix fills in as plans are costed."}}}
	}
	var total int64
	for _, s := range ordered {
		total += s.total
	}
	items := []*screensv1.PagePanelItem{}
	legend := []*screensv1.PageLink{}
	for _, s := range ordered {
		if pct := budgetpage.Percentage(s.total, total); pct >= 7 {
			items = append(items, Text(fmt.Sprintf("%d%%", pct)))
		}
		legend = append(legend, &screensv1.PageLink{Text: s.label + budgetpage.CompactIn(currency, s.total)})
	}
	return Panel(title, append(items, Links(legend...))...)
}

// Recent is the recent-activity card: each line, or the words for none,
// then the card's link when it has one.
func Recent(title string, lines []string, link string) *screensv1.PageBlock {
	list := []*screensv1.PageLink{}
	for _, l := range lines {
		list = append(list, &screensv1.PageLink{Text: l})
	}
	if len(list) == 0 {
		list = append(list, &screensv1.PageLink{Text: "No decisions recorded yet."})
	}
	if link != "" {
		list = append(list, &screensv1.PageLink{Text: "View all activity", Href: link})
	}
	return Panel(title, Links(list...))
}

// Panel is a panel block.
func Panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// Text is a text line.
func Text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// Heading is a heading line.
func Heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

// Links is a list of links.
func Links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

// MonthFilter is the month select, January to December.
func MonthFilter(months []string, month int) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: "month", Label: "Month", Value: fmt.Sprint(month)}
	for i := 1; i <= 12; i++ {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: fmt.Sprint(i), Label: months[i]})
	}
	return f
}

// YearFilter is the year select: the year options and the asked year,
// latest first.
func YearFilter(years []string, fy string) *screensv1.PageFilter {
	all := append([]string{}, years...)
	found := false
	for _, y := range all {
		found = found || y == fy
	}
	if !found {
		all = append(all, fy)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(all)))
	f := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: fy, Caption: "Financial Year"}
	for _, y := range all {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: y, Label: y})
	}
	return f
}
