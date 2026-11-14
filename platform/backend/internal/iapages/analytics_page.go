package iapages

import (
	"net/url"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
)

const verifiersExplained = "Turnaround is measured from submission to decision. Sample accuracy is the share of this verifier's certifications that a second verifier confirmed."

// analyticsPage is pages/ia/verification_analytics.html as the feed reads
// it: the window filter, the quality strip, then each section — under its
// heading with its table (a page at a time), or, when it has nothing, a
// panel of its empty message.
func analyticsPage(d analyticsData, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Verification", Title: "Verification Analytics",
		Description: "What gets returned and why, who keeps sending weak evidence, how fast verifiers turn work round, and how certifications hold up on a second look.",
		Actions:     []*screensv1.PageAction{pageheader.Download("Export decisions", "/ia/analytics/export?window="+strconv.Itoa(d.window))}}
	options := make([]*screensv1.PageFilterOption, 0, len(analyticsWindows))
	for _, w := range analyticsWindows {
		options = append(options, &screensv1.PageFilterOption{Value: strconv.Itoa(w), Label: "Last " + strconv.Itoa(w) + " days"})
	}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			{Name: "window", Value: strconv.Itoa(d.window), Caption: "Window", Options: options}}}}},
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Verification quality", Metrics: []*screensv1.PageMetric{
			{Label: "Decisions", Value: strconv.Itoa(d.decisions), Note: "verified or returned"},
			{Label: "Returned", Value: strconv.Itoa(d.returned), Note: "sent back for correction"},
			{Label: "Return rate", Value: percent(d.rate), Note: "of decisions"},
			{Label: "Verifiers active", Value: strconv.Itoa(len(d.verifiers)), Note: "in this window"},
		}}}},
	}
	section := func(title, empty string, explained string, columns []string, rows [][]string, param string, lead []*screensv1.PageBlock) {
		if len(rows) == 0 {
			items := []*screensv1.PagePanelItem{}
			if explained != "" {
				items = append(items, text(explained))
			}
			items = append(items, text(empty))
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}})
			return
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: title}})
		if explained != "" {
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{text(explained)}}}})
		}
		blocks = append(blocks, lead...)
		blocks = append(blocks, pagedTable(columns, rows, param, query)...)
	}

	reasons := make([][]string, 0, len(d.reasons))
	for _, r := range d.reasons {
		reasons = append(reasons, []string{closedschools.Collapse(r.reason), strconv.Itoa(r.count), percent(r.share)})
	}
	section("Why work is returned", "No work was returned in this window.", "",
		[]string{"Reason", "Returns", "Share"}, reasons, "reasons_page", nil)

	trend := make([][]string, 0, len(d.trend))
	bars := []*screensv1.PagePanelItem{}
	for _, t := range d.trend {
		trend = append(trend, []string{t.month, strconv.Itoa(t.decisions), strconv.Itoa(t.returned), percent(t.rate)})
		bars = append(bars, text(t.month), text(percent(t.rate)))
	}
	section("Return rate by month", "Verification decisions appear here as they are made.", "",
		[]string{"Month", "Decisions", "Returned", "Rate"}, trend, "trend_page",
		[]*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: bars}}}})

	section("Submitters, highest return rate first", "Staff submissions appear here once verified or returned.", "",
		[]string{"Staff", "Submitted", "Returned", "Rate"}, rateCells(d.submitters), "submitters_page", nil)
	section("Partners, highest return rate first", "Partner-delivered work appears here once verified or returned.", "",
		[]string{"Partner", "Submitted", "Returned", "Rate"}, rateCells(d.partners), "partners_page", nil)

	verifiers := make([][]string, 0, len(d.verifiers))
	for _, v := range d.verifiers {
		avg, accuracy := "—", "—"
		if v.avgHours != nil {
			avg = floatText(*v.avgHours)
		}
		if v.accuracy != nil {
			accuracy = percent(*v.accuracy)
		}
		verifiers = append(verifiers, []string{closedschools.Collapse(v.name), strconv.Itoa(v.verified), avg, percent(v.within24), strconv.Itoa(v.sampled), accuracy})
	}
	section("Verifiers", "Verifier turnaround appears here once work is verified in this window.", verifiersExplained,
		[]string{"Verifier", "Verified", "Avg hours", "Within 24h", "Sampled", "Sample accuracy"}, verifiers, "verifiers_page", nil)

	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: AnalyticsPath}
}

func percent(n int) string { return strconv.Itoa(n) + "%" }

func rateCells(rows []rateRow) [][]string {
	out := make([][]string, 0, len(rows))
	for _, r := range rows {
		out = append(out, []string{closedschools.Collapse(r.name), strconv.Itoa(r.submitted), strconv.Itoa(r.returned), percent(r.rate)})
	}
	return out
}

// pagedTable is one section's table, its first column a label and the rest
// figures, a page of rows at a time, with its pager when it runs to more
// than one page.
func pagedTable(columns []string, rows [][]string, param string, query url.Values) []*screensv1.PageBlock {
	size := rules.TablePageSize
	number, pages := closedschools.PageOf(query.Get(param), len(rows), size)
	t := &screensv1.PageTable{}
	for i, c := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: i > 0})
	}
	for _, r := range rows[(number-1)*size : min(number*size, len(rows))] {
		cells := make([]*screensv1.PageCell, 0, len(r))
		for _, c := range r {
			cells = append(cells, &screensv1.PageCell{Text: c})
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(param, number, pages, len(rows), size, query, rules.QueryKeysNotPassed))
	}
	return out
}
