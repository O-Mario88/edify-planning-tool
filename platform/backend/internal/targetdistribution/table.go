package targetdistribution

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// tableColumns are the master table's heads.
var tableColumns = []string{"#", "Priority group", "Milestone", "Activity", "Uganda target", "Unit", "Core", "Client",
	"Allocation method", "Owner", "Balance", "Verified delivery", "Status", ""}

// paginate is Paginator(rows, 50).get_page(page): a page that is not a
// whole number is the first, one out of range the last (a page int() would
// read where Go does not is handed on). It returns the page's
// rows, the first row's number and the footer. The links carry the rest of
// the ask in the order it came, which Go no longer knows when it holds more
// than the year: that ask is handed on when the footer has links.
func paginate(rows []*row, sel selection) ([]*row, int, *screensv1.PageBlock, error) {
	pages := max(1, (len(rows)+pageSize-1)/pageSize)
	number := 1
	switch digits := strings.TrimLeft(sel.page, "0123456789") == ""; {
	case sel.page == "":
	case digits:
		n, err := strconv.Atoi(sel.page)
		number = n
		if err != nil || n < 1 || n > pages {
			number = pages // EmptyPage: the last page
		}
	case strings.IndexFunc(sel.page, func(r rune) bool {
		return r > unicode.MaxASCII || unicode.IsSpace(r) || r == '+' || r == '-' || r == '_'
	}) >= 0:
		// int() reads these ("+2", " 2", "1_0", "٢") where Go's digits do not.
		return nil, 0, nil, fmt.Errorf("the page %q: %w", sel.page, errPassOn)
	}
	start := (number - 1) * pageSize
	end := min(start+pageSize, len(rows))
	caption := fmt.Sprintf("Showing 0 of %d milestones", len(rows))
	if len(rows) > 0 {
		caption = fmt.Sprintf("Showing %d–%d of %d milestones", start+1, end, len(rows))
	}
	items := []*screensv1.PagePanelItem{text(caption)}
	if pages > 1 {
		rest := url.Values{}
		for key, values := range sel.query {
			if key != "page" {
				rest[key] = values
			}
		}
		if len(rest) > 1 {
			return nil, 0, nil, fmt.Errorf("a pager over a many-part ask: %w", errPassOn)
		}
		prefix := "?"
		if encoded := rest.Encode(); encoded != "" {
			prefix += encoded + "&"
		}
		link := func(label string, n int) *screensv1.PageLink {
			return &screensv1.PageLink{Text: label, Href: prefix + "page=" + strconv.Itoa(n)}
		}
		var run []*screensv1.PageLink
		flush := func() {
			if len(run) > 0 {
				items = append(items, linksItem(run...))
				run = nil
			}
		}
		if number > 1 {
			run = append(run, link("‹", number-1))
		}
		for n := 1; n <= pages; n++ {
			switch {
			case n == number:
				flush()
				items = append(items, text(strconv.Itoa(n)))
			case n >= number-2 && n <= number+2:
				run = append(run, link(strconv.Itoa(n), n))
			}
		}
		if number < pages {
			run = append(run, link("›", number+1))
		}
		flush()
	}
	return rows[start:end], start + 1, panel("", items...), nil
}

// tableBlock is the page of rows, or the empty state when none match.
func (ws *workspace) tableBlock(rows []*row, first int, sel selection) *screensv1.PageBlock {
	cols := []*screensv1.PageColumn{}
	for _, c := range tableColumns {
		cols = append(cols, &screensv1.PageColumn{Label: c})
	}
	t := &screensv1.PageTable{Columns: cols}
	if len(rows) == 0 {
		t.EmptyMessage = "Clear or adjust the filters to continue."
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{
			{Text: "No milestones match these filters. Clear or adjust the filters to continue."}}}}
	}
	for i, r := range rows {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: ws.cells(r, first+i, sel)})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

// cells is one milestone's row as the feed reads it.
func (ws *workspace) cells(r *row, number int, sel selection) []*screensv1.PageCell {
	unit := r.unit
	if unit == "" {
		unit = "—"
	}
	owner := r.role
	if owner == "" {
		owner = "Country owner"
	}
	method := rules.MethodLabels[r.method]
	if method == "" {
		method = r.method
	}
	balance := "—"
	switch {
	case r.remaining != nil:
		balance = figure(r.remaining)
	case r.state != nil && !r.state.summable && r.state.balanced:
		balance = "Aligned"
	case r.state != nil && !r.state.summable:
		balance = "Open"
	}
	// The details drawer's labels and values, read as the page draws them.
	details := feeddom.JoinParts("View milestone details", "Activity", r.activity, "Unit", unit, "Portfolio",
		"Core "+orDash(r.core)+" · Client "+orDash(r.client), "Method", method, "Owner", owner)
	return []*screensv1.PageCell{
		{Text: strconv.Itoa(number)}, {Text: r.priority.title}, {Text: r.title, Strong: true}, {Text: r.activity},
		{Text: orDash(r.target)}, {Text: unit}, {Text: orDash(r.core)}, {Text: orDash(r.client)}, {Text: method},
		{Text: owner}, {Text: balance}, {Text: allocations.MeterValue(r.plan) + " " + r.rollup()}, {Text: r.status},
		{Text: sel.rowAction(ws, r) + " " + details},
	}
}

// rowAction is the row's button, as its words read.
func (sel selection) rowAction(ws *workspace, r *row) string {
	if sel.role.Distributor && ws.published && r.method == fieldCascade && !r.needsConfirmation {
		switch r.status {
		case "Distributed":
			return "Review · Locked allocation"
		case "Ready to approve":
			return "Approve · Zero balance"
		case "Balance open":
			return "Continue" + orDash(r.remaining) + " remaining"
		}
		return "Distribute · To Program Leads"
	}
	if sel.role.Director && !ws.published {
		return "Confirm source figure"
	}
	return "—"
}

// rollup is the approved allocations' roll-up beside the meter.
func (r *row) rollup() string {
	p := r.progress
	switch {
	case p == nil:
		return "—"
	case p.summable:
		s := figure(p.actual) + " of " + figure(p.plan)
		if p.pct != nil {
			s += " · " + pyFloat(*p.pct) + "%"
		}
		return s
	}
	return fmt.Sprintf("%d %s · %d %s met", p.holders, plural(p.holders, "holder", "s"), p.quartersAchieved,
		plural(p.quartersAchieved, "qtr", "s"))
}
