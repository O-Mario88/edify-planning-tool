package adminops

import (
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
)

// teamPlanRow is one row as Team Plans writes it.
type teamPlanRow struct {
	cells   []*screensv1.PageCell
	overdue bool
	kind    string
}

// teamPlansPage is pages/admin_ops/team_plans.html as the feed reads it.
// Rows the role and overdue filters drop are left out after the read, so the
// health strip counts what is listed; the table shows the first page size
// of them.
func teamPlansPage(list []planRow, next map[string]todos.NextAction, people map[string]person, partners map[string]string,
	o planOptions, q map[string]string, fy string, today time.Time, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Platform Operations", Title: "Team Plans",
		Description: "Everyone's My Plan, consolidated. Open the owning workspace when you need to execute an action."}
	role := strings.TrimSpace(q["role"])
	overdueOnly := slices.Contains([]string{"1", "true", "yes"}, strings.TrimSpace(q["overdue"]))
	rows := []teamPlanRow{}
	for _, x := range list {
		owner := people[x.Owner]
		if role != "" && owner.role != role {
			continue
		}
		// is_overdue asks whether the status class is "done", which no
		// class is: every past planned date reads as overdue.
		overdue := x.Planned != nil && time.Date(x.Planned.Year(), x.Planned.Month(), x.Planned.Day(), 0, 0, 0, 0, time.UTC).Before(today)
		if overdueOnly && !overdue {
			continue
		}
		rows = append(rows, teamPlanRow{cells: planCells(x, next[x.ID], owner, partners, today), overdue: overdue, kind: next[x.ID].Action})
	}
	overdue, noNext := 0, 0
	for _, r := range rows {
		if r.overdue {
			overdue++
		}
		if r.kind == "" || r.kind == "view" {
			noNext++
		}
	}
	blocks := []*screensv1.PageBlock{
		panel("", []string{"Consolidated Team Plans view — open the relevant Planning, My Plan, approval or finance workspace to execute an action."}),
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Team plan attention", Metrics: []*screensv1.PageMetric{
			{Label: "Overdue plan items", Value: strconv.Itoa(overdue), Note: "Needs immediate recovery"},
			{Label: "No next action", Value: strconv.Itoa(noNext), Note: "Needs a clear owner step"},
		}}}},
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			choice("role", "Role", "All roles", q["role"], pairs(o.roles)),
			choice("activity_type", "Activity Type", "All types", q["activity_type"], pairs(o.types)),
			choice("status", "Workflow State", "All states", q["status"], pairs(o.statuses)),
			choice("district", "District", "All districts", q["district"], o.districts),
		}}}},
	}
	if len(rows) == 0 {
		blocks = append(blocks, panel("", []string{"No plan records match these filters",
			"This is a real result, not an error: for " + fy + " nothing matches. Widen the filters, or check whether plans are being generated at all."}))
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: TeamPlansPath}
	}
	shown := rows[:min(len(rows), rules.TeamPlans.PageSize)]
	t := &screensv1.PageTable{Columns: columns("User", "Role", "Activity", "School ID", "School / Cluster / Project", "Planned",
		"Status", "Next Action", "Executor", "Budget", "IA", "Finance", "Updated", "Inspect")}
	number, pages := closedschools.PageOf(query.Get("rows_page"), len(shown), rules.TablePageSize)
	for _, r := range shown[(number-1)*rules.TablePageSize : min(number*rules.TablePageSize, len(shown))] {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: r.cells})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("rows_page", number, pages, len(shown), rules.TablePageSize, query, nil))
	}
	if len(rows) > rules.TeamPlans.PageSize {
		blocks = append(blocks, panel("", []string{"Showing the first " + strconv.Itoa(len(shown)) + " rows — narrow the filters to see the rest."}))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: TeamPlansPath}
}

func pairs(values []string) [][2]string {
	out := make([][2]string, len(values))
	for i, v := range values {
		out[i] = [2]string{v, v}
	}
	return out
}

// choice is a select as the feed reads it: its value only when one of its
// options is chosen.
func choice(name, caption, blank, asked string, options [][2]string) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Caption: caption, Options: []*screensv1.PageFilterOption{{Value: "", Label: blank}}}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if o[0] == asked && asked != "" {
			f.Value = asked
		}
	}
	return f
}

// planCells is one row's cells. The school's ID is the one the web fills in
// for its {% school_code %} tag; the school is a link for a reader who may
// open profiles (the page's readers all may).
func planCells(x planRow, na todos.NextAction, owner person, partners map[string]string, today time.Time) []*screensv1.PageCell {
	user := owner.name
	if user == "" {
		user = orDefault(x.Owner, "—")
	}
	kind, ok := rules.TeamPlans.ActivityTypes[x.Type]
	if !ok {
		kind = x.Type
	}
	target := ""
	switch {
	case x.School != nil:
		target = *x.School
	case x.Cluster != nil:
		target = *x.Cluster
	}
	if target == "" {
		target = orDefault(x.Project, "—")
	}
	code, targetCell := "—", &screensv1.PageCell{Text: collapse(target)}
	if x.SchoolID != nil {
		code = closedschools.SchoolCode(x.Code)
		targetCell.Href = "/schools/" + *x.SchoolID
	}
	planned := "—"
	if x.Planned != nil {
		planned = x.Planned.Format("02 Jan")
	}
	executor := orDefault(owner.name, "Unassigned")
	if x.Delivery == "partner" {
		executor = "Partner"
		if n, ok := partners[x.Partner]; ok {
			executor = n
		}
	}
	budget := "Costed"
	if x.CostMissing {
		budget = "Cost missing"
	}
	return []*screensv1.PageCell{
		{Text: collapse(user)}, {Text: orDefault(owner.role, "—")}, {Text: kind}, {Text: code}, targetCell,
		{Text: planned}, {Text: planStatus(x, today)}, {Text: collapse(orDefault(na.Text, "—"))}, {Text: collapse(executor)},
		{Text: budget}, {Text: pyTitle(strings.ReplaceAll(orDefault(x.IAState, "not required"), "_", " "))},
		{Text: financeState(x)}, {Text: x.Updated.In(zone).Format("02 Jan 15:04")},
		{Text: "Open · Report", Href: "/my-plan/" + x.ID + "?support=1"},
	}
}
