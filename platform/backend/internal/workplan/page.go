package workplan

import (
	"regexp"
	"strconv"
	"strings"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// pageSize is TABLE_PAGE_SIZE: every table's rows a page.
const pageSize = 50

func itoa(n int) string { return strconv.Itoa(n) }

func collapse(s string) string { return closedschools.PyCollapse(s) }

// comma is |intcomma (and format(n, ",")) of a whole number.
func comma(n int64) string {
	s := strconv.FormatInt(n, 10)
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return sign + s
}

func intStrings(ns []int) []string {
	out := make([]string, len(ns))
	for i, n := range ns {
		out[i] = itoa(n)
	}
	return out
}

// plural is |pluralize:"y,ies" after "activit".
func activities(n int) string {
	if n == 1 {
		return comma(int64(n)) + " activity"
	}
	return comma(int64(n)) + " activities"
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: collapse(t)}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func panel(p *screensv1.PagePanel) *screensv1.PageBlock {
	if p.Badges == nil {
		p.Badges = []*screensv1.PageBadge{}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
}

// figure is page_blocks.FIGURE: a figure standing on its own.
var figure = regexp.MustCompile(`^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$`)

var pagerCaption = regexp.MustCompile(`^Showing\s+\d`)

// paired is page_blocks._paired over a panel's text lines: a label line
// followed by its figure is one data row; consecutive rows share a list.
func paired(lines []string) []*screensv1.PagePanelItem {
	out := []*screensv1.PagePanelItem{}
	hasLetter := func(s string) bool { return strings.IndexFunc(s, unicode.IsLetter) >= 0 }
	for i := 0; i < len(lines); i++ {
		if i+1 < len(lines) && !pagerCaption.MatchString(lines[i]) && hasLetter(lines[i]) &&
			figure.MatchString(strings.TrimSpace(lines[i+1])) {
			row := &screensv1.PageDataRow{Label: lines[i], Value: strings.TrimSpace(lines[i+1])}
			if n := len(out); n > 0 && out[n-1].GetRows() != nil {
				out[n-1].GetRows().Rows = append(out[n-1].GetRows().Rows, row)
			} else {
				out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{row}}}})
			}
			i++
			continue
		}
		out = append(out, text(lines[i]))
	}
	return out
}

func (v *view) page(path string) *screensv1.GetPageResponse {
	st := v.s
	base := st.base()
	blocks := []*screensv1.PageBlock{}
	if w := v.door.Workspace; w != nil {
		tabs := []*screensv1.PageLinkTab{}
		for _, s := range w.Sections {
			tabs = append(tabs, &screensv1.PageLinkTab{Label: s.Label, Href: s.URL, Active: s.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{
			Tabs: tabs, Label: w.Label, Scrolls: true}}})
	}
	if st.isPL {
		tabs := []*screensv1.PageLinkTab{}
		for _, pair := range rules.ScopeTabLabels {
			tabs = append(tabs, &screensv1.PageLinkTab{Label: pair[1],
				Href: link(base, kv{"scope", pair[0]}, kv{"responsible", ""}), Active: st.scope == pair[0]})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}})
	}
	blocks = append(blocks, v.approvalPanel(), v.viewTabs(), v.filters())
	if st.flag != "" {
		blocks = append(blocks, v.flagChip())
	}
	blocks = append(blocks, v.summaryBlocks()...)
	blocks = append(blocks, v.strip())
	for _, b := range v.bands {
		blocks = append(blocks, panel(&screensv1.PagePanel{Items: paired([]string{
			b.label, activities(b.count), "UGX " + comma(b.cost),
			itoa(b.completed) + " completed", itoa(b.atRisk) + " at risk"})}))
	}
	if t := v.fyTotals; t != nil {
		blocks = append(blocks, panel(&screensv1.PagePanel{Items: paired([]string{
			"FY " + st.fy + " total", itoa(t.count) + " activities", "UGX " + comma(t.cost),
			itoa(t.completed) + " completed", itoa(t.atRisk) + " at risk"})}))
	}
	blocks = append(blocks, panel(&screensv1.PagePanel{Title: "Detailed Activity Plan — " + st.periodLabel(),
		Items: []*screensv1.PagePanelItem{links(&screensv1.PageLink{Text: "Back to Summary", Href: "#work-plan-summary"})}}))
	blocks = append(blocks, v.detail()...)

	response := &screensv1.GetPageResponse{Header: v.header(), Blocks: blocks, WebPath: path}
	for _, r := range v.rows {
		if r.canPick {
			response.Selection = &screensv1.PageSelection{Noun: "activities selected", Actions: []*screensv1.PageSelectionAction{
				{Label: "Reschedule", Href: "/activity-selection/reschedule", Param: "ids", Joined: true},
				{Label: "Cancel", Href: "/activity-selection/cancel", Param: "ids", Joined: true},
			}}
			break
		}
	}
	return response
}

func (v *view) header() *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "Planning & Execution",
		Title:       "Work Plan",
		Description: "Review all planned Activities, responsible staff, execution status and plan-derived costs across the selected period.",
		Actions:     []*screensv1.PageAction{},
	}
	if v.door.Export {
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: "export_excel", Label: "Export Excel", Enabled: true,
			Href: "/work-plan/export.xlsx?" + requestQuery(v.query)})
	}
	if v.door.AddActivity {
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: "add_non_school_activity", Label: "Add Non-School Activity",
			Enabled: true, Href: "/work-plan/add", Drawer: true})
	}
	return h
}

// approvalPanel is the CD → RVP approval section: its status pill and the
// one line under it.
func (v *view) approvalPanel() *screensv1.PageBlock {
	a := v.approval
	tone := "plain"
	switch a.status {
	case "approved_by_rvp":
		tone = "good"
	case "returned_by_rvp":
		tone = "caution"
	}
	p := &screensv1.PagePanel{Title: "FY " + v.s.fy + " Work Plan approval",
		Badges: []*screensv1.PageBadge{{Text: collapse(a.label), Tone: tone}}, Items: []*screensv1.PagePanelItem{}}
	line := ""
	switch {
	case a.note != "":
		line = "RVP note: " + a.note
	case len(a.issues) > 0 && a.canSubmit:
		line = strings.Join(a.issues, " ")
	case a.status == "submitted_to_rvp":
		line = "Submitted for regional review. The RVP can inspect the plan rows or export the complete workbook."
	case a.status == "approved_by_rvp":
		line = "Approved plan and annual budget baseline are locked."
	}
	if collapse(line) != "" {
		p.Items = append(p.Items, text(line))
	}
	return panel(p)
}

func (v *view) viewTabs() *screensv1.PageBlock {
	st := v.s
	base := st.base()
	month, quarter := 10, "Q1"
	if st.fy == st.operational {
		month, quarter = int(st.today.Month()), currentQuarter(st.today)
	}
	tabs := []*screensv1.PageLinkTab{
		{Label: rules.ViewTabLabels["month"], Href: link(base, kv{"view", "month"}, kv{"period", itoa(month)}, kv{"flag", ""}), Active: st.view == "month"},
		{Label: rules.ViewTabLabels["quarter"], Href: link(base, kv{"view", "quarter"}, kv{"period", quarter}, kv{"flag", ""}), Active: st.view == "quarter"},
		{Label: rules.ViewTabLabels["fy"], Href: link(base, kv{"view", "fy"}, kv{"period", ""}, kv{"flag", ""}), Active: st.view == "fy"},
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}}
}

type option struct{ value, label string }

// selectFilter is a select as the feed reads it: its value is the first
// option marked selected, else the first option.
func selectFilter(name, label string, options []option, selected func(string) bool) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label, Options: []*screensv1.PageFilterOption{}}
	chosen := false
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: collapse(o.label)})
		if !chosen && selected(o.value) {
			f.Value, chosen = o.value, true
		}
	}
	if !chosen && len(options) > 0 {
		f.Value = options[0].value
	}
	return f
}

func pairsOf(first option, pairs [][2]string) []option {
	out := []option{first}
	for _, p := range pairs {
		out = append(out, option{p[0], p[1]})
	}
	return out
}

func (v *view) filters() *screensv1.PageBlock {
	st := v.s
	is := func(value string) func(string) bool { return func(o string) bool { return o == value } }
	years := []option{}
	for _, y := range fyOptions(st.today) {
		years = append(years, option{y, "FY " + y})
	}
	fs := []*screensv1.PageFilter{selectFilter("fy", "Fiscal year", years, is(st.fy))}
	switch st.view {
	case "month":
		months := []option{}
		for _, m := range fyMonthOrder {
			months = append(months, option{itoa(m), monthLabel(st.fyInt, m)})
		}
		fs = append(fs, selectFilter("period", "Month", months, is(itoa(st.month))))
	case "quarter":
		quarters := []option{}
		for _, q := range quarterOrder {
			quarters = append(quarters, option{q, q})
		}
		fs = append(fs, selectFilter("period", "Quarter", quarters, is(st.quarter)))
	}
	fs = append(fs,
		selectFilter("status", "Activity status", pairsOf(option{"", "All active statuses"}, rules.Statuses), is(st.status)),
		selectFilter("responsible", "Responsible person", pairsOf(option{"", "All staff"}, v.responsible), is(st.responsible)),
		selectFilter("project", "Project", pairsOf(option{"", "All projects"}, v.projects), is(st.project)),
		selectFilter("activity_type", "Activity type", pairsOf(option{"", "All types"}, rules.ActivityTypes), is(st.activityType)),
		selectFilter("executor", "Executor", pairsOf(option{"", "Staff and partners"}, rules.DeliveryTypes), is(st.executor)),
	)
	hidden := map[string]string{"view": st.view, "fy_prev": st.fy}
	if st.isPL {
		hidden["scope"] = st.scope
	}
	if st.flag != "" {
		hidden["flag"] = st.flag
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: fs, Hidden: hidden}}}
}

// flagChip is the "Showing: …" chip and its Show all link.
func (v *view) flagChip() *screensv1.PageBlock {
	return panel(&screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		text("Showing: " + rules.FlagLabels[v.s.flag]),
		links(&screensv1.PageLink{Text: "Show all", Href: link(v.s.base(), kv{"flag", ""})}),
	}})
}

func (v *view) scopeLabel() string {
	if label, ok := rules.ScopeLabels[v.s.role]; ok {
		return label
	}
	if v.s.isPL && v.s.scope == "team" {
		return rules.TeamScopeLabel
	}
	return rules.OwnScopeLabel
}

// summaryBlocks is partials/work_plan/plan_summary.html.
func (v *view) summaryBlocks() []*screensv1.PageBlock {
	st := v.s
	out := []*screensv1.PageBlock{panel(&screensv1.PagePanel{
		Title: "Activity Plan Summary — " + st.periodLabel(), Subtitle: v.scopeLabel(),
		Items: []*screensv1.PagePanelItem{links(&screensv1.PageLink{Text: "See Details", Href: "#work-plan-detail"})},
	})}
	if n := v.missingTotal; n > 0 {
		word := "activities"
		if n == 1 {
			word = "activity"
		}
		out = append(out, panel(&screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			text(itoa(n) + " " + word + " need cost setup. Totals include recorded costs only; no missing rates are estimated.")}}))
	}
	labels := [2]string{rules.SchoolGroupLabel, rules.NonSchoolGroupLabel}
	for gi := range 2 {
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: labels[gi]}})
		list := v.summary[gi]
		number, pages := 1, max(1, (len(list)+pageSize-1)/pageSize)
		rows := []*screensv1.PageRow{}
		for _, bk := range list[:min(pageSize, len(list))] {
			unit := bk.unitDisplay
			if bk.unitNote != "" {
				unit += " " + bk.unitNote
			}
			rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: collapse(bk.label)}, {Text: comma(int64(bk.count))}, {Text: collapse(unit)}, {Text: comma(bk.cost)},
			}})
		}
		if len(list) == 0 {
			rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: "No " + strings.ToLower(labels[gi]) + " planned in this period."}}})
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: labels[gi] + " subtotal"}, {Text: comma(int64(v.totals[gi].count))}, {Text: ""}, {Text: comma(v.totals[gi].cost)},
		}})
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Columns: []*screensv1.PageColumn{{Label: "Activity"}, {Label: "Number of Activities", Numeric: true},
				{Label: "Unit Cost (UGX)", Numeric: true}, {Label: "Total Cost (UGX)", Numeric: true}},
			Rows: rows,
		}}})
		if pages > 1 {
			out = append(out, closedschools.PagerPanel("section_rows_page-"+itoa(gi+1), number, pages, len(list), pageSize, v.query, nil))
		}
	}
	total := v.totals[0].count + v.totals[1].count
	cost := v.totals[0].cost + v.totals[1].cost
	out = append(out, panel(&screensv1.PagePanel{Items: paired([]string{
		"Grand total", comma(int64(total)) + " activities", "UGX " + comma(cost)})}))
	return out
}

func (v *view) strip() *screensv1.PageBlock {
	st := v.s
	base := st.base()
	values := []int64{int64(v.planned), int64(v.thisMonth), v.budget, int64(v.pending), int64(v.missing), int64(v.atRisk)}
	hrefs := []string{
		link(base, kv{"flag", ""}),
		link(base, kv{"view", "month"}, kv{"period", itoa(int(st.today.Month()))}, kv{"flag", ""}),
		link(base, kv{"flag", ""}),
		link(base, kv{"flag", "pending_approval"}),
		link(base, kv{"flag", "cost_missing"}),
		link(base, kv{"flag", "at_risk"}),
	}
	figures := []schoolprofile.StripFigure{}
	for i, m := range rules.Strip {
		value := comma(values[i])
		if m.Unit == "money_ugx" {
			value = "UGX " + value
		}
		figures = append(figures, schoolprofile.StripFigure{Label: m.Label, Value: value, Link: hrefs[i]})
	}
	// The strip writes a sum of a million or more short ("UGX 3.83M"),
	// as every strip does (kpi_metrics.kpi_value).
	return schoolprofile.Strip("Work plan context", figures)
}

var detailColumns = []string{"Activity Date", "Activity", "School ID", "School Name", "District", "Cluster Name",
	"Activity Purpose", "SSA Intervention", "Previous SSA Score", "Delivery Mode", "Person Responsible", "Cost",
	"Planned Period", "Status", "Action"}

// detail is partials/work_plan/detail_tables.html: one page of rows and,
// past one page, the pager.
func (v *view) detail() []*screensv1.PageBlock {
	param := rules.Table.DetailPageParam
	asked := 1
	if raw := v.query.Get(param); raw != "" {
		if n, ok := closedschools.PyInt(raw); ok {
			asked = max(1, n)
		}
	}
	total := len(v.rows)
	pages := max(1, (total+pageSize-1)/pageSize)
	number := min(asked, pages)
	shown := v.rows[min((number-1)*pageSize, total):min(number*pageSize, total)]
	selectable := false
	for _, r := range shown {
		selectable = selectable || r.canPick
	}
	t := &screensv1.PageTable{Rows: []*screensv1.PageRow{}}
	for _, c := range detailColumns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, r := range shown {
		t.Rows = append(t.Rows, v.detailRow(r, selectable))
	}
	if len(shown) == 0 {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: "No activities planned No matching activities are planned in the selected period."}}})
		t.EmptyMessage = "No matching activities are planned in the selected period."
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(param, number, pages, total, pageSize, v.query, nil))
	}
	return out
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

func (v *view) detailRow(r *row, selectable bool) *screensv1.PageRow {
	st := v.s
	date := r.dateLabel
	if r.dayOff != nil {
		date += r.dayOff.label() + ": reschedule"
	}
	school := &screensv1.PageCell{Text: "—"}
	if r.schoolName != "" {
		school.Text = collapse(r.schoolName)
		if ref := pyStrip(r.schoolCode); ref != "" && v.door.Opens["school_profile"] {
			school.Href = "/schools/" + quoteAll(ref)
		}
	}
	focus := r.focus
	if focus == "" {
		focus = "Not linked"
	}
	if r.verdict != "" {
		focus += " " + r.verdict
		if r.deviation != "" {
			focus += " Planner's reason: " + r.deviation
		}
	}
	cost := "Cost setup required"
	if !r.costMissing {
		cost = "UGX " + comma(r.cost)
		if r.costNote != "" {
			cost += " " + r.costNote
		}
	}
	if len(r.lines) > 0 {
		cost += " Breakdown"
		for _, l := range r.lines {
			cost += l.label + ": UGX " + comma(l.amount)
		}
	}
	cells := []*screensv1.PageCell{
		{Text: collapse(date)}, {Text: collapse(r.word)}, {Text: collapse(orDash(r.schoolCode))}, school,
		{Text: collapse(orDash(r.district))}, {Text: collapse(orDash(r.cluster))}, {Text: collapse(r.purpose)},
		{Text: collapse(focus)}, {Text: collapse(orDash(r.score))}, {Text: collapse(r.mode)},
		{Text: collapse(r.responsible)}, {Text: collapse(cost)}, {Text: collapse(st.periodLabel())},
		{Text: r.status, Tone: "primary", Badge: true},
		{Actions: v.rowActions(r)},
	}
	out := &screensv1.PageRow{Cells: cells}
	if r.dayOff != nil {
		out.Tone = "dayoff"
	}
	if selectable && r.canPick {
		place := r.schoolName
		if place == "" {
			place = r.cluster
		}
		label := "Select " + r.word
		if place != "" {
			label += " at " + place
		}
		out.PickId, out.PickLabel = r.a.id, label
	}
	return out
}

// quoteAll is urllib.parse.quote(s, safe=""): everything but letters,
// digits and "_.-~" escaped.
func quoteAll(s string) string {
	var b strings.Builder
	for _, c := range []byte(s) {
		if c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '.' || c == '-' || c == '~' {
			b.WriteByte(c)
			continue
		}
		b.WriteString("%" + strings.ToUpper(strconv.FormatInt(int64(c)>>4, 16)) + strings.ToUpper(strconv.FormatInt(int64(c)&15, 16)))
	}
	return b.String()
}

// rowActions is the Action cell: the reader's own open work as Complete,
// Reschedule, Cancel and View details in one menu; another link and View
// details in a menu; else the link on its own as a button, View details
// under it where it is a different page.
func (v *view) rowActions(r *row) []*screensv1.PageAction {
	a := r.act
	details := "/my-plan/" + r.a.id
	canAct := opens(v.door, a.url)
	canView := opens(v.door, details)
	item := func(key, label, href, reason string, drawer bool) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: collapse(label), Enabled: true, Href: href, Reason: reason, Drawer: drawer, Primary: key == "button"}
	}
	out := []*screensv1.PageAction{}
	switch {
	case canAct && a.own:
		if a.complete {
			out = append(out, item("menu", "Complete", "/my-plan/"+r.a.id+"/complete-drawer", "Upload the evidence and complete this activity", true))
		}
		out = append(out, item("menu", a.text, "/my-plan/"+r.a.id+"/reschedule-drawer", a.description, true),
			item("danger", "Cancel", "/my-plan/"+r.a.id+"/cancel-drawer", "Cancel this activity", true))
		if canView {
			out = append(out, item("menu", "View details", details, "", false))
		}
	case canAct && canView && a.url != details:
		out = append(out, item("menu", a.text, a.url, a.description, a.drawer), item("menu", "View details", details, "", false))
	default:
		if canAct {
			out = append(out, item("button", a.text, a.url, a.description, a.drawer))
		}
		if (canView && !canAct) || (canView && a.url != details) {
			out = append(out, item("button", "View details", details, "", false))
		}
	}
	return out
}
