package mytargets

import (
	"context"
	"errors"
	"fmt"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// pageRows is the paginated tables' page size; a list longer than one page
// is handed on (its pager is not drawn).
const pageRows = 50

// contract is what the page reads of the reader's approved allocations: the
// contract over the month, each quarter and the year
// (allocation_period_matrix), and their milestones' projection
// (personal_milestone_targets).
type contract struct {
	periods    []allocations.Contract
	milestones []allocations.Milestone
}

func (c contract) annual() allocations.Contract { return c.periods[len(c.periods)-1] }

func readContract(ctx context.Context, db schooldirectory.Querier, pg *page) (contract, error) {
	var c contract
	mStart, mEnd := targets.MonthRange(pg.fy, pg.month)
	windows := []allocations.Window{{Start: mStart, End: mEnd.AddDate(0, 0, -1), Part: true}}
	for _, q := range []string{"Q1", "Q2", "Q3", "Q4"} {
		s, e := targets.QuarterRange(pg.fy, q)
		windows = append(windows, allocations.Window{Start: s, End: e.AddDate(0, 0, -1), Part: true})
	}
	windows = append(windows, allocations.Year(pg.fy))
	for _, w := range windows {
		period, err := allocations.ReadWindow(ctx, db, pg.p, pg.fy, w, pg.now)
		if err != nil {
			return c, err
		}
		c.periods = append(c.periods, period)
	}
	if len(c.annual().Rows) > pageRows {
		return c, errPassOn
	}
	if pg.p.StaffProfileID == "" {
		// personal_milestone_targets is read only for a People record.
		return c, nil
	}
	milestones, err := allocations.Personal(ctx, db, pg.p.StaffProfileID, pg.fy, pg.month)
	if errors.Is(err, allocations.ErrNotDrawn) {
		return c, errPassOn
	}
	if err != nil {
		return c, err
	}
	if len(milestones) > pageRows {
		return c, errPassOn
	}
	c.milestones = milestones
	return c, nil
}

// floatText is a float as the template prints it (Python's str()).
func floatText(f *float64) string {
	if f == nil {
		return ""
	}
	return allocations.Repr(*f)
}

// distributedSummary is partials/hr/distributed_summary.html over the
// year's contract.
func (c contract) distributedSummary() []*screensv1.PageBlock {
	return allocations.SummaryBlocks(c.annual())
}

// milestoneRows are the approved milestones' rows of the agreed matrix.
func (c contract) milestoneRows() []*screensv1.PageRow {
	out := []*screensv1.PageRow{}
	for _, m := range c.milestones {
		cells := []*screensv1.PageCell{{Text: m.Title + " " + m.Priority}}
		for _, cell := range m.Cells {
			cells = append(cells, &screensv1.PageCell{Text: allocations.FloatFormat(cell.Target.Rat(), -2)},
				&screensv1.PageCell{Text: allocations.FloatFormat(cell.Actual.Rat(), -2)}, &screensv1.PageCell{Text: pctText(cell.Pct)})
		}
		out = append(out, &screensv1.PageRow{Cells: cells})
	}
	return out
}

// matrix is the contract over each reporting period
// ("Distributed allocations by reporting period"), nothing without rows.
func (c contract) matrix(pg *page) []*screensv1.PageBlock {
	annual := c.annual()
	if len(annual.Rows) == 0 {
		return nil
	}
	byID := make([]map[string]allocations.Row, len(c.periods))
	for i, period := range c.periods {
		byID[i] = map[string]allocations.Row{}
		for _, r := range period.Rows {
			byID[i][r.ID] = r
		}
	}
	share := func(p *float64) string {
		if p == nil {
			return "—"
		}
		return floatText(p) + "%"
	}
	rows := []*screensv1.PageRow{}
	for _, r := range annual.Rows {
		cells := []*screensv1.PageCell{{Text: r.Title}}
		for i := range c.periods {
			v := byID[i][r.ID]
			cells = append(cells, &screensv1.PageCell{Text: v.TargetDec.String()}, &screensv1.PageCell{Text: v.ActualDec.String()},
				&screensv1.PageCell{Text: share(v.Pct)})
		}
		rows = append(rows, &screensv1.PageRow{Cells: cells})
	}
	overall := []*screensv1.PageCell{{Text: "Overall progress"}}
	for _, period := range c.periods {
		overall = append(overall, &screensv1.PageCell{Text: share(period.Pct)})
	}
	rows = append(rows, &screensv1.PageRow{Cells: overall})
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Distributed allocations by reporting period"}}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: matrixColumns(pg), Rows: rows}}},
	}
}

// planningRows are the portfolio's planning feed: each approved milestone.
func (c contract) planningRows(fy string) []portfolioRow {
	out := []portfolioRow{}
	for _, m := range c.milestones {
		out = append(out, portfolioRow{title: m.Title, action: "Plan work",
			url: "/planning?fy=" + fy + "&priority_allocation=" + m.AllocationID})
	}
	return out
}

// table is "My Strategic Milestone Allocations".
func (c contract) table() []*screensv1.PageBlock {
	note := "Only approved allocations appear here. Actuals come from canonical source records and cannot be typed."
	if len(c.milestones) == 0 {
		return []*screensv1.PageBlock{milestonesPanel()}
	}
	cols := []*screensv1.PageColumn{}
	for _, col := range []struct {
		label   string
		numeric bool
	}{{"Strategic Priority / Milestone", false}, {"Target source", false}, {"Month plan / actual", true},
		{"Quarter target / actual", true}, {"FY target / actual", true}, {"Progress", true}, {"Remaining", true},
		{"Status", false}, {"Linked Activities", true}, {"Data source", false}} {
		cols = append(cols, &screensv1.PageColumn{Label: col.label, Numeric: col.numeric})
	}
	rows := []*screensv1.PageRow{}
	for _, m := range c.milestones {
		progress := "0"
		if m.Progress != nil {
			progress = floatText(m.Progress)
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: m.Title + m.Priority}, {Text: "Approved Milestone Allocation"},
			{Text: m.MonthPlan.String() + " / " + m.MonthActual.String()},
			{Text: m.QuarterPlan.String() + " / " + m.QuarterActual.String()},
			{Text: m.FYPlan.String() + " / " + m.FYActual.String()},
			{Text: progress + "%"}, {Text: m.Remaining.String()}, {Text: m.Class.Label},
			{Text: strconv.Itoa(m.Linked)}, {Text: m.DataSource},
		}})
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "My Strategic Milestone Allocations",
			Items: []*screensv1.PagePanelItem{text(note)}}}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: rows}}},
	}
}

// matrixColumns are the period matrix's heads as the feed reads them.
func matrixColumns(pg *page) []*screensv1.PageColumn {
	monthName := targets.MonthLabel(pg.fy, pg.month)
	for i, ch := range monthName {
		if ch == ' ' {
			monthName = monthName[:i]
			break
		}
	}
	n, _ := strconv.Atoi(pg.fy)
	heads := [][2]string{{monthName, "Monthly"}}
	for _, q := range []string{"Q1", "Q2", "Q3", "Q4"} {
		heads = append(heads, [2]string{q, targets.QuarterLabel(pg.fy, q)})
	}
	heads = append(heads, [2]string{fmt.Sprintf("FY %d/%s", n-1, pg.fy[len(pg.fy)-2:]), "Full Year"})
	cols := []*screensv1.PageColumn{{Label: "Cumulative progress by time period Target · achieved · share"}}
	for _, h := range heads {
		cols = append(cols, &screensv1.PageColumn{Label: h[0] + " " + h[1]})
	}
	for range heads {
		for _, l := range []string{"Target", "Achieved", "%"} {
			cols = append(cols, &screensv1.PageColumn{Label: l})
		}
	}
	return cols
}
