package budgetpage

import (
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

type view struct {
	a      ask
	role   string
	export bool
	groups []*group
	team   []member
	now    time.Time
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
	plan := panel("Activity cost plan",
		"Costs come directly from scheduled planned activities and are grouped by activity and item. Training and meeting tables show sessions and participants.")
	out = append(out, plan)
	if len(v.groups) == 0 {
		plan.GetPanel().Items = []*screensv1.PagePanelItem{
			text("Choose another time view or schedule an activity to create its budget automatically."),
		}
		return out
	}
	var total, staff int64
	for _, g := range v.groups {
		total += g.total
		staff += g.staffTotal
	}
	out = append(out, panel("", "", figure("Grand total", ugx(total))), v.ledger(staff, total))
	source := "My planned activities"
	if a.budgetScope == "team" {
		source = "Team planned activities"
	}
	return append(out, panel("", "", text("Source: "+source+" · Total: "+ugx(total))))
}

// ledger is partials/budgets/budget_group_tables.html as the feed reads
// it: every group's band, its column names, its rows and its subtotal, then
// the grand total.
func (v view) ledger(staff, total int64) *screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, g := range v.groups {
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
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}
