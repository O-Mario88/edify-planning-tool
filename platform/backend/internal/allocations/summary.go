package allocations

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// SummaryRows is the distributed summary's page (TABLE_PAGE_SIZE): a
// contract longer than this is drawn with a pager the summary does not draw,
// so its page is handed on.
const SummaryRows = 50

// SummaryBlocks is partials/hr/distributed_summary.html over a contract as
// the feed reads it: the verified achievement (or that no score is
// configured), then a row a milestone (its title, the contract's scope, the
// target with its unit, the verified figure and the achievement).
func SummaryBlocks(c Contract) []*screensv1.PageBlock {
	score := "No configured score for this reporting scope"
	if c.Pct != nil {
		score = Repr(*c.Pct) + "% verified achievement"
	}
	cols := []*screensv1.PageColumn{}
	for _, l := range []string{"Priority", "Scope", "Target", "Verified", "Achievement"} {
		cols = append(cols, &screensv1.PageColumn{Label: l})
	}
	rows := []*screensv1.PageRow{}
	for _, r := range c.Rows {
		achievement := "Not configured"
		if r.Pct != nil {
			achievement = Repr(*r.Pct) + "%"
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r.Title}, {Text: c.Scope}, {Text: FloatFormat(r.Target, -2) + " " + r.Unit},
			{Text: FloatFormat(r.Actual, -2)}, {Text: achievement},
		}})
	}
	if len(rows) == 0 {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: "No approved distributed priorities in this record."}}})
	}
	panel := &screensv1.PagePanel{Title: "Distributed priority performance", Items: []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Text{Text: score}}}}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: panel}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: rows}}},
	}
}
