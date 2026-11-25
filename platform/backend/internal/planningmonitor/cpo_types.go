package planningmonitor

import (
	"slices"
	"sort"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// cpoTypeColumns are _types.html's heads, every view's in order.
var cpoTypeColumns = []string{"School Type", "Schools", "Fully Planned", "Partly Planned", "Awaiting a Partner's Date", "Not Yet Planned",
	"With a Partner", "Staff Half Planned", "Duplicate Bookings", "More Than 2 + 2", "Visits Needed", "Staff Target", "Planned by Staff",
	"Partner Target", "Assigned to Partners", "Planned by Partners", "Visits Remaining", "Visit Coverage", "Trainings Needed", "Staff Target",
	"Planned by Staff", "Partner Target", "Assigned to Partners", "Planned by Partners", "Trainings Planned", "Trainings Remaining",
	"No Training Planned"}

// cellOf reads an element as the feed reads a table cell: its words and the
// first link in it.
func cellOf(parts ...any) *screensv1.PageCell {
	td := feeddom.El("td", "", parts...)
	table := feeddom.El("table", "", feeddom.El("thead", "", feeddom.El("tr", "", feeddom.El("th", "", "x"))),
		feeddom.El("tbody", "", feeddom.El("tr", "", td)))
	blocks := feeddom.Walk(feeddom.El("div", "", table), nil)
	return blocks[0].GetTable().GetRows()[0].GetCells()[0]
}

func plain(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }

// typeRow is service._type_row as _types.html draws it.
func typeRow(key, label string, t cpoTally, total bool, query, typeQuery string, dupBookings, overPackage int) *screensv1.PageRow {
	needsVisits, needsTrainings := total, total
	if !total {
		needsVisits, needsTrainings = need(key).visits() > 0, need(key).trainings() > 0
	}
	isCore := key == "core"
	fig := func(n int, table, list string) *feeddom.Node { return figureLink(cpoFmt(n), query, key, table, list) }
	link := func(n int, href string) *screensv1.PageCell {
		if n == 0 {
			return plain("0")
		}
		return &screensv1.PageCell{Text: cpoFmt(n), Href: href}
	}
	dash := plain("—")
	cells := []*screensv1.PageCell{}
	head := []any{feeddom.El("span", "", label)}
	if !needsVisits {
		head = append(head, feeddom.El("span", "cpo-hint", feeddom.El("span", "", "outreach only")))
	}
	status := t.n("planned_full") + t.n("planned_part") + t.partnerToPlan() + t.n("unplanned")
	if unaccounted := t.n("visit_schools") - status; unaccounted != 0 {
		head = append(head, feeddom.El("span", "cpo-flagged", feeddom.El("span", "",
			cpoFmtRaw(unaccounted)+" school"+pluralize(unaccounted, "", "s")+" not accounted for")))
	}
	cells = append(cells, cellOf(head...), cellOf(fig(t.n("schools"), "", "all")))
	if needsVisits {
		cells = append(cells, cellOf(fig(t.n("planned_full"), "", "fully_planned")), cellOf(fig(t.n("planned_part"), "partly-planned", "")),
			link(t.partnerToPlan(), cpoPath+"table/partners?school_type="+key+"&"+typeQuery),
			link(t.n("unplanned"), cpoPath+"table/not-planned?school_type="+key+"&"+typeQuery))
	} else {
		cells = append(cells, dash, dash, dash, dash)
	}
	cells = append(cells, link(t.n("with_partner"), cpoPath+"table/partners?school_type="+key+"&"+typeQuery))
	if isCore || total {
		parts := []any{fig(t.n("core_staff_done"), "", "core_staff_visits")}
		if isCore {
			parts = append(parts, " ", feeddom.El("span", "", paren(t.n("core_staff_done"), t.n("schools"))))
		}
		cells = append(cells, cellOf(parts...))
	} else {
		cells = append(cells, dash)
	}
	if isCore || !needsVisits {
		cells = append(cells, dash)
	} else {
		cells = append(cells, link(dupBookings, cpoPath+"table/duplicates?school_type="+key+"&"+typeQuery))
	}
	if isCore || total {
		cells = append(cells, link(overPackage, cpoPath+"table/duplicates?school_type=core&"+typeQuery))
	} else {
		cells = append(cells, dash)
	}
	withShare := func(n int, table, list string, part, whole int) *screensv1.PageCell {
		return cellOf(feeddom.El("span", "", fig(n, table, list)), " ", feeddom.El("span", "", paren(part, whole)))
	}
	if needsVisits {
		cells = append(cells,
			cellOf(fig(t.n("visit_slots"), "", "all")),
			cellOf(fig(t.n("staff_expected"), "", "staff_queue")),
			withShare(t.n("staff"), "visits", "", t.n("staff"), t.n("staff_expected")),
			cellOf(fig(t.n("partner_expected"), "", "partner_queue")),
			withShare(t.n("partner_assigned"), "partners", "", t.n("partner_assigned"), t.n("partner_expected")),
			withShare(t.n("partner_scheduled"), "", "partner_dated", t.n("partner_scheduled"), t.n("partner_expected")),
			cellOf(fig(max(0, t.n("visit_slots")-t.planned()), "not-planned", "")),
			plain(pct(t.planned(), t.n("visit_slots"))))
	} else {
		for i := 0; i < 8; i++ {
			cells = append(cells, dash)
		}
	}
	if needsTrainings {
		cells = append(cells,
			cellOf(fig(t.n("training_slots"), "", "training_due")),
			cellOf(fig(t.n("training_staff_slots"), "", "training_due")),
			withShare(t.n("training_staff"), "trainings", "", t.n("training_staff"), t.n("training_staff_slots")),
			cellOf(fig(t.n("training_partner_slots"), "", "core")),
			withShare(t.n("training_partner_assigned"), "partners", "", t.n("training_partner_assigned"), t.n("training_partner_slots")),
			withShare(t.n("training_partner"), "trainings", "", t.n("training_partner"), t.n("training_partner_slots")),
			withShare(t.n("training"), "trainings", "", t.n("training"), t.n("training_slots")),
			cellOf(fig(max(0, t.n("training_slots")-t.n("training")), "no-training", "")),
			link(t.n("no_training"), cpoPath+"table/no-training?school_type="+key+"&"+typeQuery))
	} else {
		for i := 0; i < 9; i++ {
			cells = append(cells, dash)
		}
	}
	return &screensv1.PageRow{Cells: cells}
}

// cpoFmtRaw is a figure as the template prints an int: no separators.
func cpoFmtRaw(n int) string { return itoa(n) }

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	b := []byte{}
	for n > 0 {
		b = append([]byte{byte('0' + n%10)}, b...)
		n /= 10
	}
	if neg {
		b = append([]byte{'-'}, b...)
	}
	return string(b)
}

// cpoTypeBlocks is _types.html: the heading, the three readings and the
// table of the schools by their own type, every type together last.
func cpoTypeBlocks(snap *cpoSnapshot) []*screensv1.PageBlock {
	page := rules.CountryOversight.Page
	query := snap.filters.query(nil)
	typeQuery := snap.filters.query(map[string]string{"school_type": ""})
	byType := snap.tree.byType
	order := []string{}
	for _, t := range rules.TypeOrder {
		if _, ok := byType[t]; ok || snap.filters.schoolType == "" {
			order = append(order, t)
		}
	}
	extra := []string{}
	for t := range byType {
		if !slices.Contains(rules.TypeOrder, t) {
			extra = append(extra, t)
		}
	}
	sort.Strings(extra)
	order = append(order, extra...)
	cols := []*screensv1.PageColumn{}
	for _, c := range cpoTypeColumns {
		cols = append(cols, &screensv1.PageColumn{Label: c})
	}
	table := &screensv1.PageTable{Columns: cols}
	dup, over := 0, 0
	for _, t := range order {
		v := cpoTally(byType[t])
		if v == nil {
			v = cpoTally(cpoBlank())
		}
		d, o := v.n("duplicates"), 0
		if t == "core" {
			d, o = 0, v.n("duplicates")
		}
		dup, over = dup+d, over+o
		table.Rows = append(table.Rows, typeRow(t, typeLabel(t), v, false, query, typeQuery, d, o))
	}
	if len(order) > 1 {
		table.Rows = append(table.Rows, typeRow("", "All school types", cpoTally(snap.tree.country), true, query, typeQuery, dup, over))
	}
	if len(table.Rows) == 0 {
		table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{plain("No school in this selection.")}}}
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Planned and Not Yet Planned by School Type"}}},
		cpoChips("School type figures", page.TypeViews),
		{Kind: &screensv1.PageBlock_Table{Table: table}},
	}
}
