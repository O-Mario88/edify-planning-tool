package budgetpage

import (
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

type view struct {
	a      ask
	role   string
	export bool
	groups []*group
	team   []member
	now    time.Time

	// The country's Budget.
	country   bool
	wf        workflow
	fin       financeHealth
	districts []district
}

func (v view) header() *screensv1.PageHeader {
	roleLabel := v.role
	if l, ok := rules.RoleLabels[v.role]; ok {
		roleLabel = l
	}
	h := &screensv1.PageHeader{
		Eyebrow:     "Finance",
		Title:       "Budget",
		Description: v.a.selected.title + " · FY " + strconv.Itoa(v.a.fy) + " · " + roleLabel,
	}
	if v.export {
		// The feed writes a drawer's address with its query in key order,
		// blank values dropped (the district, for a reader with none).
		q := url.Values{}
		q.Set("fy", strconv.Itoa(v.a.fy))
		q.Set("budget_scope", v.a.budgetScope)
		q.Set("date", v.a.anchor.Format(time.DateOnly))
		h.Actions = []*screensv1.PageAction{{
			Key: "export", Label: "Export", Enabled: true, Drawer: true,
			Href: "/budget/export-drawer?" + q.Encode(),
		}}
	}
	return h
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

func text(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
}

func figure(label, value string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{
		Rows: []*screensv1.PageDataRow{{Label: label, Value: value}},
	}}}
}

func cells(texts ...string) *screensv1.PageRow {
	r := &screensv1.PageRow{}
	for _, t := range texts {
		r.Cells = append(r.Cells, &screensv1.PageCell{Text: t})
	}
	return r
}

func (v view) blocks() []*screensv1.PageBlock {
	a := v.a
	base := "?fy=" + strconv.Itoa(a.fy) + "&date=" + a.anchor.Format(time.DateOnly) + "&period="
	tabs := &screensv1.PageLinkTabs{}
	for _, t := range []struct{ key, label string }{{"month", "Monthly Budget"}, {"quarter", "Quarterly Budget"}, {"fy", "Annual Budget"}} {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{
			Label: t.label, Active: a.period == t.key,
			Href: base + t.key + "&budget_scope=" + a.budgetScope + "&district=",
		})
	}
	years := schooldirectory.FYOptions(v.now)
	fy := strconv.Itoa(a.fy)
	if !contains(years, fy) {
		years = append(years, fy)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(years)))
	year := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: fy}
	for _, y := range years {
		year.Options = append(year.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	out := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
			Filters: []*screensv1.PageFilter{year},
			Hidden:  map[string]string{"period": a.period, "budget_scope": a.budgetScope},
		}}},
		panel("", "", text("Calculated from the costed activities in weekly plans. Month, quarter and annual budgets roll up those planned costs.")),
	}
	if v.country && v.wf.priorPending != "" {
		out = append(out, panel("", "", text(v.wf.priorPending+" budget is still awaiting RVP review. Preparing the current month is not blocked — periods are independent.")))
	}
	if len(v.team) > 0 {
		people := "staff members"
		if len(v.team) == 1 {
			people = "staff member"
		}
		items := []*screensv1.PagePanelItem{text(strconv.Itoa(len(v.team)) + " " + people)}
		for _, m := range v.team {
			items = append(items, text(m.name), figure(activities(m.activities), ugx(m.total)))
		}
		out = append(out, panel("Team cost summary",
			"Each person’s planned activity cost for this "+strings.ToLower(a.selected.label)+".", items...))
	}
	const planHelp = "Costs come directly from scheduled planned activities and are grouped by activity and item. Training and meeting tables show sessions and participants."
	if len(v.groups) == 0 {
		out = append(out, panel("Activity cost plan", planHelp,
			text("Choose another time view or schedule an activity to create its budget automatically.")))
		return append(out, v.countryBlocks()...)
	}
	if v.country {
		// The district filter beside the heading: the feed reads the heading's
		// note as the panel's text, then the filter.
		out = append(out, panel("Activity cost plan", "", text(planHelp)), v.districtFilter())
	} else {
		out = append(out, panel("Activity cost plan", planHelp))
	}
	var total, staff int64
	for _, g := range v.groups {
		total += g.total
		staff += g.staffTotal
	}
	out = append(out, panel("", "", figure("Grand total", ugx(total))), v.ledger(staff, total))
	source := map[string]string{
		"my": "My planned activities", "team": "Team planned activities", "country": "Scheduled planned activities",
	}[a.budgetScope]
	out = append(out, panel("", "", text("Source: "+source+" · Total: "+ugx(total))))
	return append(out, v.countryBlocks()...)
}

func (v view) districtFilter() *screensv1.PageBlock {
	f := &screensv1.PageFilter{Name: "district", Label: "District", Value: "",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All districts"}}}
	for _, d := range v.districts {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: d.id, Label: d.name})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{f},
		Hidden: map[string]string{
			"fy": strconv.Itoa(v.a.fy), "date": v.a.anchor.Format(time.DateOnly), "period": v.a.period,
		},
	}}}
}

// countryBlocks are the country's Finance Health and, for a month, its
// approval workflow and reconciliation.
func (v view) countryBlocks() []*screensv1.PageBlock {
	if !v.country {
		return nil
	}
	f := v.fin
	pct := int64(0)
	if f.requested != 0 {
		pct = pyPercentage(f.disbursed, f.requested)
	}
	money := ugx
	fy := strconv.Itoa(v.a.fy)
	out := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Section{Section: "Finance Health, FY " + fy}},
		schoolprofile.Strip("Advance Pipeline", []schoolprofile.StripFigure{
			{Label: "Requested", Value: money(f.requested), Helper: "Every advance in the pipeline"},
			{Label: "Pending Confirmation", Value: money(f.pending)},
			{Label: "Confirmed for Advance", Value: money(f.confirmed)},
			{Label: "Disbursed", Value: money(f.disbursed), Helper: strconv.FormatInt(pct, 10) + "% of requested"},
			{Label: "Accounted", Value: money(f.accounted)},
			{Label: "Returned", Value: money(f.returned)},
		}),
		{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{
			Title: "Advances Requested by Quarter", Subtitle: "UGX requested against each quarter's activities",
			Categories: []string{"Q1", "Q2", "Q3", "Q4"},
			Series: []*screensv1.PageSeries{{Name: "Requested (UGX)", Values: []float64{
				float64(f.quarters[0]), float64(f.quarters[1]), float64(f.quarters[2]), float64(f.quarters[3]),
			}}},
			AxisTitle: "UGX requested",
		}}},
	}
	if v.a.period != "month" {
		return out
	}
	w := v.wf
	month := strconv.Itoa(w.month)
	links := &screensv1.PageLinks{Links: []*screensv1.PageLink{
		{Text: "View plan sources", Href: "/country-budget/plan-sources?fy=" + fy + "&month=" + month, Drawer: true},
		{Text: "Submitted budgets", Href: "/country-budget/history?fy=" + fy},
	}}
	if isRVP(v.role) && !isCD(v.role) && w.status == "submitted_to_rvp" {
		links.Links = append(links.Links, &screensv1.PageLink{
			Text: "Return", Drawer: true,
			Href: "/country-budget/return?budget_id=" + url.QueryEscape(w.id) + "&fy=" + fy + "&month=" + month,
		})
	}
	approved := int64(0)
	if in(rules.Country.ApprovedLimitStatuses, w.status) {
		approved = w.operationalRequirement
	}
	r := w.rec
	return append(out,
		panel("Monthly Budget Approval", "Status: "+w.approvalStatus()+" · "+rules.Country.Months[w.month]+" FY "+fy,
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: links}}),
		panel("", "", text("Country operational request: "+ugx(w.total)+". New submissions contain only costs from planned activities. Previously submitted amounts remain in Submitted budgets.")),
		panel("Disbursement and Accountability", "", text("Actual spending")),
		schoolprofile.Strip("Performance overview", []schoolprofile.StripFigure{
			{Label: "Approved Operating Limits", Value: ugxCompact(approved)},
			{Label: "Committed", Value: ugxCompact(r.committed)},
			{Label: "Amount Disbursed", Value: ugxCompact(r.disbursed)},
			{Label: "Actual Accounted Spend", Value: ugxCompact(r.accounted)},
			{Label: "Returned Balance", Value: ugxCompact(r.returned)},
			{Label: "Reimbursements", Value: ugxCompact(r.reimbursed)},
		}),
	)
}

// ledger is partials/budgets/budget_group_tables.html as the feed reads
// it: every group's band, its column names, its rows and its subtotal, then
// the grand total.
func (v view) ledger(staff, total int64) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Rows: ledgerRows(v.groups, staff, total)}}}
}

// ledgerRows is the ledger's rows: each group's band, column names, rows
// and subtotal, then the grand total.
func ledgerRows(gs []*group, staff, total int64) []*screensv1.PageRow {
	t := &screensv1.PageTable{}
	for _, g := range gs {
		count, people := "No. of Days", "No. of Persons"
		switch g.kind {
		case "meeting":
			count, people = "Meetings", "Participants"
		case "training":
			count, people = "Training sessions", "Participants"
		case "admin":
			count, people = "Quantity", "—"
		}
		t.Rows = append(t.Rows, cells(g.label+" "+activities(len(g.activityIDs))),
			cells("Item", count, people, "Rate / Unit", "Staff cost", "Activity"))
		for _, r := range g.rows {
			n := len(r.dates)
			if g.kind == "meeting" || g.kind == "training" {
				n = len(r.activityIDs)
			}
			var heads int64
			for _, c := range r.people {
				heads += c
			}
			headText := "—"
			if heads != 0 {
				headText = strconv.FormatInt(heads, 10)
			}
			staffText := ugx(r.staffTotal)
			if r.vendorTotal != 0 && r.staffTotal == 0 {
				staffText = "—"
			}
			t.Rows = append(t.Rows, cells(r.item, strconv.Itoa(n), headText, ugx(r.rate), staffText, ugx(r.total)))
		}
		t.Rows = append(t.Rows, cells(g.label+" subtotal", ugx(g.staffTotal), ugx(g.total)))
	}
	t.Rows = append(t.Rows, cells("Grand total", ugx(staff), ugx(total)))
	return t.Rows
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}
