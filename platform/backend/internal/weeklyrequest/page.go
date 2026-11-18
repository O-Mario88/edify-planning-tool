package weeklyrequest

import (
	"fmt"
	"net/url"
	"slices"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func link(t, href string) *screensv1.PageLink { return &screensv1.PageLink{Text: t, Href: href} }

func figureRow(label, value string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{
		Rows: []*screensv1.PageDataRow{{Label: label, Value: value}}}}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

func plural(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// The query keys in the filter form's order: the order a submitted form, and
// so a tab's link, writes them.
var formOrder = []string{"fy", "quarter", "month", "week", "district", "staff", "request_type", "status", "period_tab", "budget_scope"}

// queryWithout is the page's query without key, in the form's order, ending
// "&" when anything is left (team_tab_query).
func queryWithout(query url.Values, key string) string {
	parts := []string{}
	for _, k := range formOrder {
		if v := query.Get(k); k != key && v != "" {
			parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(v))
		}
	}
	if len(parts) == 0 {
		return ""
	}
	return strings.Join(parts, "&") + "&"
}

func (v *view) header() *screensv1.PageHeader {
	h := &screensv1.PageHeader{Title: "Weekly Advance Request",
		Description: "Review planned costs, submit weekly advances, and track approval and receipt."}
	if v.r.AddActivity {
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: "add_non_school_activity", Label: "Add Non-School Activity",
			Enabled: true, Href: "/work-plan/add", Drawer: true})
	}
	if v.r.Export {
		q := []string{"fy=" + url.QueryEscape(v.fy)}
		if v.a.district != "" {
			q = append(q, "district="+url.QueryEscape(v.a.district))
		}
		if v.base.staff != "" {
			q = append(q, "staff="+url.QueryEscape(v.base.staff))
		}
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: "export", Label: "Export", Enabled: true,
			Href: "/fund-requests/weekly/export-drawer?" + strings.Join(q, "&"), Drawer: true})
	}
	h.Actions = append(h.Actions, &screensv1.PageAction{Key: "budget", Label: "Budget", Enabled: true, Href: "/budget"})
	return h
}

func options(pairs [][2]string) []*screensv1.PageFilterOption {
	out := make([]*screensv1.PageFilterOption, 0, len(pairs))
	for _, p := range pairs {
		out = append(out, &screensv1.PageFilterOption{Value: p[0], Label: p[1]})
	}
	return out
}

func (v *view) filters() *screensv1.PageBlock {
	years := schooldirectory.FYOptions(v.today)
	if !slices.Contains(years, v.fy) {
		years = append(years, v.fy)
	}
	slices.Sort(years)
	slices.Reverse(years)
	fy := [][2]string{}
	for _, y := range years {
		fy = append(fy, [2]string{y, "FY " + y})
	}
	quarters := [][2]string{{"Q1", "Q1"}, {"Q2", "Q2"}, {"Q3", "Q3"}, {"Q4", "Q4"}}
	monthOpts := [][2]string{}
	for _, m := range fiscalMonths {
		monthOpts = append(monthOpts, [2]string{months[m], months[m]})
	}
	weekOpts := [][2]string{}
	for _, w := range v.weeks {
		weekOpts = append(weekOpts, [2]string{w.Format("2006-01-02"), w.Format("Jan 02") + " - " + w.AddDate(0, 0, 6).Format("Jan 02")})
	}
	// The week select marks no option (its choice is Alpine's x-model), so
	// the feed reads its first.
	week := ""
	if len(weekOpts) > 0 {
		week = weekOpts[0][0]
	}
	fs := []*screensv1.PageFilter{
		{Name: "fy", Label: "Fiscal year", Value: v.fy, Options: options(fy)},
		{Name: "quarter", Label: "Quarter", Value: v.quarter, Options: options(quarters)},
		{Name: "month", Label: "Month", Value: v.monthName, Options: options(monthOpts)},
		{Name: "week", Label: "Week", Value: week, Options: options(weekOpts)},
	}
	if v.showTeamFilters {
		fs = append(fs,
			&screensv1.PageFilter{Name: "district", Label: "District", Value: v.a.district,
				Options: options(append([][2]string{{"", "All districts"}}, v.districts...))},
			&screensv1.PageFilter{Name: "staff", Label: "Staff", Value: v.base.staff,
				Options: options(append([][2]string{{"", "All staff"}}, v.staffOptions...))})
	}
	fs = append(fs,
		&screensv1.PageFilter{Name: "request_type", Label: "Request type", Value: v.a.requestType, Options: options(requestTypes)},
		&screensv1.PageFilter{Name: "status", Label: "Status", Value: v.a.status, Options: options(statusOptions)})
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: fs, Hidden: map[string]string{"period_tab": "week"}}}}
}

// money and compact write amounts in the request's country's currency
// (docs/migration/80, §19).
func (v *view) money(n int64) string { return budgetpage.In(budgetpage.CurrencyCode(v.p.Country), n) }

func (v *view) compact(n int64) string {
	return budgetpage.CompactIn(budgetpage.CurrencyCode(v.p.Country), n)
}

func requests(n int) string { return fmt.Sprintf("%d request%s", n, plural(n, "", "s")) }

func (v *view) strip() *screensv1.PageBlock {
	figures := []schoolprofile.StripFigure{
		{Label: "Total Requested This Month", Value: v.compact(v.thisMonth), Helper: "No prior-month baseline"},
		{Label: "Awaiting Approval", Value: v.compact(v.awaiting.total), Helper: requests(v.awaiting.count)},
		{Label: "Approved", Value: v.compact(v.approved.total), Helper: requests(v.approved.count)},
		{Label: "Ready for Disbursement", Value: v.compact(v.ready.total), Helper: requests(v.ready.count)},
		{Label: "Returned for Review", Value: v.compact(v.returned.total), Helper: requests(v.returned.count)},
		{Label: "Accountability Pending", Value: v.compact(v.pendingAcct.total), Helper: requests(v.pendingAcct.count)},
	}
	b := schoolprofile.Strip("Request and budget context", figures)
	if v.lastMonth > 0 {
		// The trend replaces the line under the figure; the line is kept as
		// its note (components/context_metrics.html).
		delta := roundHalfUp(float64(v.thisMonth-v.lastMonth) * 100 / float64(v.lastMonth))
		value := fmt.Sprintf("%d%%", max(delta, -delta))
		switch {
		case delta > 0:
			value = "↗ " + value
		case delta < 0:
			value = "↘ " + value
		}
		m := b.GetStrip().GetMetrics()[0]
		m.Helper, m.Note, m.Tone = value, "vs Last Month", "neutral"
	}
	return b
}

func (v *view) teamTabsBlock() *screensv1.PageBlock {
	if len(v.teamTabs) == 0 {
		return nil
	}
	base := "?" + queryWithout(v.a.query, "staff")
	tabs := []*screensv1.PageLinkTab{}
	for _, t := range v.teamTabs {
		tabs = append(tabs, &screensv1.PageLinkTab{Label: t[1], Href: base + "staff=" + url.QueryEscape(t[0]), Active: t[2] != ""})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}}
}

// chip is partials/fund_requests/_wfr_status_chip.html's words.
func chip(w *weekRequest) string {
	switch w.status {
	case "pending_responsible_confirmation":
		return "Draft"
	case "submitted_to_pl":
		return "Awaiting PL Approval"
	case "submitted_to_cd":
		return "Awaiting CD Approval"
	case "returned_by_pl", "returned_by_cd", "returned_by_accountant":
		return "Returned — Fix & Re-submit"
	case "confirmed_for_advance":
		return "Approved — At Accountant"
	case "self_funded":
		return "Self-funded"
	case "disbursed":
		if w.receiptConfirmed {
			return "Receipt confirmed"
		}
		return "Disbursed — awaiting receipt"
	}
	return budgetpage.PyTitle(strings.ReplaceAll(w.status, "_", " "))
}

const helpLine = "Fund requests are generated automatically from the activities scheduled in My Plan — nothing here is entered by hand."

// card is the period card on its Week tab: the request and its ledger, or
// the week's empty state.
func (v *view) card() []*screensv1.PageBlock {
	title := "Week of " + v.weekStart.Format("02 Jan") + " – " + v.weekEnd.Format("02 Jan 2006")
	head := &screensv1.PagePanel{Title: "Weekly advance request",
		Subtitle: "Costs come directly from planned activities, grouped by activity and item."}
	if m := v.mission; m != nil {
		if m.transportDays > 0 {
			state := "Arranged"
			if m.confirmed {
				state = "Confirmed"
			}
			head.Badges = append(head.Badges, &screensv1.PageBadge{Tone: "plain", Text: fmt.Sprintf(
				"Transport %s · %d day%s — paid directly to transport provider", state, m.transportDays, plural(m.transportDays, "", "s"))})
		}
		if m.nights > 0 {
			head.Badges = append(head.Badges, &screensv1.PageBadge{Tone: "plain", Text: fmt.Sprintf(
				"Accommodation · %d night%s — booked by Finance", m.nights, plural(m.nights, "", "s"))})
		}
	}
	w := v.active
	if w == nil {
		head.Items = []*screensv1.PagePanelItem{text(title), text("No activities scheduled for this week."),
			text("The fund request populates automatically the moment an activity is scheduled in My Plan — nothing to generate manually."),
			links(link("Open My Plan", "/my-plan")), text(helpLine + " Learn more")}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: head}}}
	}
	head.Items = []*screensv1.PagePanelItem{text(chip(w)), text(title)}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: head}}}
	out = append(out, v.ledgerBlocks()...)
	returned := in([]string{"returned_by_pl", "returned_by_cd", "returned_by_accountant"}, w.status)
	if returned && w.returnReason != "" {
		note := []*screensv1.PagePanelItem{text("Returned for correction"), text(w.returnReason)}
		if v.owner {
			note[0] = &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Returned for correction"}, Lead: "Returned for correction"}
			note = append(note, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Correct your weekly plan, then resubmit this request."},
				TextLinks: []*screensv1.PageLink{link("Correct your weekly plan", "/my-plan")}})
		}
		out = append(out, panel("", "", note...))
	}
	if w.fundingSource == "self_fund" {
		out = append(out, panel("", "", text("Self Fund · The same planned amount follows supervisor approval, disbursement and receipt confirmation.")))
	}
	source := link("View Source Activities", "/my-plan")
	actionQuery := "fy=" + url.QueryEscape(v.fy) + "&week=" + v.weekStart.Format("2006-01-02") +
		"&staff=" + url.QueryEscape(v.base.staff) + "&period_tab=week"
	returnLink := &screensv1.PageLink{Text: "Return", Href: "/fund-requests/weekly/" + w.id + "/return-drawer?" + actionQuery, Drawer: true}
	work := []*screensv1.PagePanelItem{}
	switch {
	case v.canApprove:
		work = append(work, links(returnLink, source))
	case v.canDisburse:
		work = append(work, links(&screensv1.PageLink{Text: "Disburse", Href: "/finance/actions/drawer?action=disburse_advance&request_id=" + w.id, Drawer: true},
			returnLink, source))
	case v.owner && (in(set4, w.status) || w.status == "not_requested"):
		work = append(work, links(source))
	case returned:
		work = append(work, text("Awaiting the requester's corrected weekly plan and resubmission."), links(source))
	case w.status == "submitted_to_pl":
		work = append(work, text("Submitted — awaiting Program Lead approval."), links(source))
	case w.status == "submitted_to_cd":
		work = append(work, text("Submitted — awaiting Country Director approval."), links(source))
	default:
		label := v.statusLabel
		if label == "" {
			label = "closed"
		}
		work = append(work, text("✓ Action completed. This weekly request is "+label+"."), links(source))
	}
	out = append(out, panel("", "", work...), panel("", "", text(helpLine), links(link("Learn more", "/help"))))
	return out
}

// ledgerBlocks is the request's submitted ledger: its grand total, then
// the table of its groups (budget_group_tables.html).
func (v *view) ledgerBlocks() []*screensv1.PageBlock {
	rows := v.ledger
	out := []*screensv1.PageBlock{}
	// The grand-total band leads the table and closes it as its last row.
	if n := len(rows); n > 0 && len(rows[n-1].GetCells()) > 0 && rows[n-1].GetCells()[0].GetText() == "Grand total" {
		cells := rows[n-1].GetCells()
		out = append(out, panel("", "", figureRow("Grand total", cells[len(cells)-1].GetText())))
	}
	return append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Rows: rows}}})
}

func (v *view) sourcesBlock() *screensv1.PageBlock {
	if len(v.sources) == 0 {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: "Source Activities from My Plan", Subtitle: "View All", EmptyMessage: "No activities scheduled in this week."}}}
	}
	items := []*screensv1.PagePanelItem{}
	for _, s := range v.sources {
		items = append(items, text(s.title), text(budgetpage.PyTitle(s.status)), text(s.location+" • "+s.date), text(s.purpose))
	}
	items = append(items, text(fmt.Sprintf("Showing %d of %d source activities", len(v.sources), len(v.sources))),
		links(link("Open My Plan", "/my-plan")))
	return panel("Source Activities from My Plan", "", items...)
}

func (v *view) insightsBlocks() []*screensv1.PageBlock {
	in := v.insights
	items := []*screensv1.PagePanelItem{
		text("This Week"), text(fmt.Sprintf("%d requests generated from My Plan", in.week.count)),
		text("Total value: " + v.money(in.week.total)),
		text("Attention Needed"), text(fmt.Sprintf("%d Items", in.attention)),
		text(fmt.Sprintf("• %d request%s awaiting responsible confirmation", in.attention, plural(in.attention, "", "s"))),
		text(fmt.Sprintf("• %d activit%s marked self-funded", in.selfFunded, plural(in.selfFunded, "y", "ies"))),
		text(in.dueHeading), text("Due on " + in.dueDate), text(in.dueTiming),
	}
	if v.r.MonthlyRequest {
		items = append(items, links(link("Prepare monthly request", "/accounts/monthly-request/")))
	}
	items = append(items, text("Budget Integrity Check"))
	if in.missingCosted == 0 {
		items = append(items, text("✓ All scheduled activities are costed."))
	} else {
		items = append(items, text(fmt.Sprintf("⚠ %d missing catalogue items.", in.missingCosted)))
	}
	items = append(items, text("Last checked: "+v.today.Format("Jan 02, 2006")))
	if v.r.Reports {
		items = append(items, links(link("View report", "/reports")))
	}
	items = append(items, text("Next Recommended Action"), text(in.action), text(in.actionDesc))
	if in.takeAction {
		items = append(items, text("Take Action"))
	}
	return []*screensv1.PageBlock{panel("Fund Request Insights", ""), panel("", "", items...)}
}

func (v *view) breakdownBlock() *screensv1.PageBlock {
	labels := []string{"This Week", "This Month", "This Quarter (" + v.quarter + ")", "This FY (" + v.fy + ")"}
	items := []*screensv1.PagePanelItem{}
	for i, t := range v.breakdown {
		items = append(items, figureRow(labels[i], v.money(t.total)), text(requests(t.count)))
	}
	return panel("Request Breakdown by Period", "", items...)
}

func page(v *view) *screensv1.GetPageResponse {
	stages := []*screensv1.PageLink{}
	for _, s := range rules.StageLabels {
		stages = append(stages, link(s, ""))
	}
	blocks := []*screensv1.PageBlock{panel("", "", links(stages...)), v.filters(),
		panel("Request totals and approval status", "This month's requested, awaiting, approved and ready-to-disburse amounts."),
		v.strip()}
	if b := v.teamTabsBlock(); b != nil {
		blocks = append(blocks, b)
	}
	blocks = append(blocks, v.card()...)
	blocks = append(blocks, v.sourcesBlock())
	blocks = append(blocks, v.insightsBlocks()...)
	blocks = append(blocks, v.breakdownBlock())
	return &screensv1.GetPageResponse{Header: v.header(), Blocks: blocks, WebPath: Path}
}
