package projectmonitoring

import (
	"fmt"
	"net/url"
	"sort"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The words below live in pages/projects/monitoring.html and
// partials/projects/monitoring_school_table.html.

const (
	describeControls = "Every school in your projects: whether it is planned by you or handed to a partner and scheduled, whether the work happened, and whether its focus SSA interventions moved. You schedule the work, assign it to a partner, and withdraw it from a partner or reassign it."
	describeWhole    = "Every school in every live project: whether the coordinator or a partner has planned it, whether the work happened, and whether its focus SSA interventions moved. The Project Coordinator schedules the work and assigns it to partners."
	describeMine     = "The schools you added to each project: whether the coordinator or a partner has planned them, whether the work happened, and whether their focus SSA interventions moved. The Project Coordinator schedules the work and assigns it to partners; you can withdraw a school you added until its project work begins."
	readOnlyNote     = "Read only, apart from withdrawing a school you added from its project before its project work begins. Scheduling a project activity, assigning one to a partner, and withdrawing a school's work from its partner or reassigning it are the Project Coordinator's — ask them for work you need at a school you added."
	emptyWhole       = "A project appears here once it is created and running. Paused and closed projects keep their history on the project's own page."
	emptyMine        = "Add a school to a project from its profile or the School Directory, and the coordinator's work at that school appears here. Schools other officers added stay with them."
	pausedNote       = "Paused — takes no new work"
)

var columns = []string{
	"Project Name", "School ID", "School Name", "District", "Training", "Purpose of Assignment",
	"SSA Intervention", "Previous SSA Score", "Current SSA Score", "SSA Improvement", "Status",
	"Activity Date", "Enrolled On", "Planning Stage", "Planned By", "Execution", "Activity Status",
	"Activity Cost", "Actions",
}

func page(v view) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{filters(v)}
	if s := v.doors.Strip; s != nil {
		tabs := make([]*screensv1.PageLinkTab, len(s.Tabs))
		for i, t := range s.Tabs {
			tabs[i] = &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active}
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{
			LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs, Label: s.Label, Scrolls: s.Scrolls}}})
	}
	blocks = append(blocks, figures(v))
	if v.workload != nil {
		blocks = append(blocks, v.workload)
	}
	switch {
	case v.open != nil:
		blocks = append(blocks, projectTabs(v), table(v))
		if !v.l.controls {
			blocks = append(blocks, panel(readOnlyNote))
		}
	case v.l.whole || v.l.controls:
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyWhole}})
	default:
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyMine}})
	}
	return &screensv1.GetPageResponse{Header: header(v), Blocks: blocks, WebPath: Path}
}

func header(v view) *screensv1.PageHeader {
	text := describeMine
	switch {
	case v.l.controls:
		text = describeControls
	case v.l.whole:
		text = describeWhole
	}
	if v.period != "" {
		text += " Activities read for " + v.period + "."
	}
	return &screensv1.PageHeader{Eyebrow: "Special Projects", Title: "Project Monitoring", Description: text}
}

func panel(text string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: text}}},
	}}}
}

// filters is _project_monitoring_filters: district, stage, year, then the
// table's other columns, each column offering the values the reader's rows
// hold (monitoring.row_filter_options).
func filters(v view) *screensv1.PageBlock {
	column := func(f [3]string) *screensv1.PageFilter {
		values := map[string]bool{}
		if pick := v.picks[f[0]]; pick != "" {
			values[pick] = true
		}
		for _, pr := range v.projects {
			for _, r := range pr.everyone {
				if value := r.value(f[0]); value != "" {
					values[value] = true
				}
			}
		}
		options := []*screensv1.PageFilterOption{{Value: "", Label: f[2]}}
		for _, value := range sortedFold(values) {
			options = append(options, &screensv1.PageFilterOption{Value: value, Label: value})
		}
		return &screensv1.PageFilter{Name: f[0], Label: f[1], Value: v.picks[f[0]], Options: options}
	}
	stage := &screensv1.PageFilter{Name: "stage", Label: "School stage", Value: v.stage}
	for _, f := range rules.StageFilters {
		stage.Options = append(stage.Options, &screensv1.PageFilterOption{Value: f[0], Label: f[1]})
	}
	fy := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: v.fy}
	for _, y := range v.options {
		fy.Options = append(fy.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	list := []*screensv1.PageFilter{column(rules.RowFilters[0]), stage, fy}
	for _, f := range rules.RowFilters[1:] {
		list = append(list, column(f))
	}
	out := &screensv1.PageFilters{Filters: list}
	if v.selected != "" {
		out.Hidden = map[string]string{"project": v.selected}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: out}}
}

// figures is the KPI strip: every project in view, then the open project's
// own activity, each figure naming the project it counts.
func figures(v view) *screensv1.PageBlock {
	schools, improved := 0, 0
	for _, pr := range v.projects {
		schools += pr.mine
		improved += pr.impact.Improved
	}
	helper := "Schools you added"
	if v.l.whole || v.l.controls {
		helper = "Enrolled in these projects"
	}
	list := []schoolprofile.StripFigure{
		{Label: "Projects", Value: intcomma(len(v.projects)), Helper: "Live projects in this lens"},
		{Label: "Schools", Value: intcomma(schools), Helper: helper},
		// Nothing is planned, awaiting a partner or delivered: no work exists.
		{Label: "Schools planned", Value: "0 / " + intcomma(schools), Helper: "By the coordinator or a partner"},
		{Label: "Awaiting partner schedule", Value: "0", Helper: "Assigned to a partner, no date yet"},
		{Label: "Schools delivered", Value: "0", Helper: "At least one activity carried out"},
		{Label: "Schools improved", Value: intcomma(improved), Helper: "Confirmed SSA movement on the target intervention"},
	}
	if v.open != nil {
		name := v.open.p.Name
		period := v.period
		if period == "" {
			period = "this financial year"
		}
		list = append(list,
			schoolprofile.StripFigure{Label: "Trainings", Value: "0 / 0", Helper: "Delivered of scheduled · " + name},
			schoolprofile.StripFigure{Label: "School visits", Value: "0 / 0", Helper: "Delivered of scheduled · " + name},
			schoolprofile.StripFigure{Label: "Other project work", Value: "0 / 0", Helper: "Nothing planned yet · " + name},
			schoolprofile.StripFigure{Label: "Who delivered", Value: "0 staff · 0 partner", Helper: "Activities in " + period + " · " + name},
		)
	}
	return schoolprofile.Strip("Performance overview", list)
}

// filterQuery is urlencode(picks), in ROW_FILTERS order.
func filterQuery(v view) string {
	parts := []string{}
	for _, f := range rules.RowFilters {
		if value := v.picks[f[0]]; value != "" {
			parts = append(parts, url.QueryEscape(f[0])+"="+url.QueryEscape(value))
		}
	}
	return strings.Join(parts, "&")
}

func projectTabs(v view) *screensv1.PageBlock {
	extra := ""
	if q := filterQuery(v); q != "" {
		extra = "&" + q
	}
	tabs := make([]*screensv1.PageLinkTab, len(v.projects))
	for i, pr := range v.projects {
		tabs[i] = &screensv1.PageLinkTab{
			Label:  fmt.Sprintf("%s %d", pr.p.Name, len(pr.rows)),
			Href:   "?project=" + pr.p.ID + "&stage=" + v.stage + "&fy=" + v.fy + extra,
			Active: pr.p.ID == v.selected,
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs, Scrolls: true}}}
}

func table(v view) *screensv1.PageBlock {
	pr := v.open
	title := pr.p.Name
	if pr.p.Code != "" {
		title += " " + pr.p.Code
	}
	pills := []string{pr.p.statusLabel()}
	if v.l.whole || v.l.controls {
		pills = append(pills, fmt.Sprintf("%d schools", pr.mine))
	} else {
		pills = append(pills, fmt.Sprintf("%d of %d schools yours", pr.mine, pr.schools))
	}
	pills = append(pills, "0 planned", "0 delivered")
	cols := make([]*screensv1.PageColumn, len(columns))
	for i, c := range columns {
		cols[i] = &screensv1.PageColumn{Label: c}
	}
	selectable := v.l.controls && in(rules.OpenStatuses, pr.p.Status) && len(pr.rows) > 0
	rows := []*screensv1.PageRow{}
	for _, r := range pr.rows {
		rows = append(rows, schoolLine(v, r, selectable))
	}
	if len(rows) == 0 {
		message := "No school in this project yet."
		switch {
		case filterQuery(v) != "":
			message = "No school in this project matches these filters."
		case v.stage != "":
			message = "No school in this project is at that stage."
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: message}}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:    title,
		Subtitle: strings.Join(pills, " "),
		Columns:  cols,
		Rows:     rows,
		Footnote: fmt.Sprintf("Not measured yet: %d of %d school%s have a baseline, a verified delivery and a confirmed follow-up.",
			pr.impact.Cohort, pr.impact.Added, plural(pr.impact.Added)),
	}}}
}

func score(f *float64) string {
	if f == nil {
		return "—"
	}
	return floatStr(*f)
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

func schoolLine(v view, r schoolRow, selectable bool) *screensv1.PageRow {
	name := &screensv1.PageCell{Text: r.e.SchoolName}
	if v.doors.Profiles {
		name.Href = "/schools/" + r.e.SchoolCode
	}
	improvement := "—"
	if c := r.improvement(); c != nil {
		improvement = floatStr(*c)
		if *c > 0 {
			improvement = "+" + improvement
		}
	}
	texts := []string{
		r.ProjectName, r.e.SchoolCode, "", orDash(r.e.District), "—", orDash(r.Purpose), orDash(r.Intervention),
		score(r.Previous), score(r.Current), improvement, rules.RowStatusLabels["awaiting_coordinator"], "—",
		dayLabel(r.e.enrolledOn()), rules.PlanLabels["not_planned"], "—", rules.ExecLabels["none"], "—", "—",
	}
	cells := make([]*screensv1.PageCell, 0, len(texts)+1)
	for i, t := range texts {
		if i == 2 {
			cells = append(cells, name)
			continue
		}
		cells = append(cells, &screensv1.PageCell{Text: t})
	}
	cells = append(cells, actions(v, r))
	row := &screensv1.PageRow{Cells: cells, Details: details(r)}
	if selectable && r.PartnerURL != "" {
		row.PickId = r.e.ID
	}
	return row
}

func actions(v view, r schoolRow) *screensv1.PageCell {
	view := "/projects/monitoring/school?enrolment=" + url.QueryEscape(r.e.ID) + "&fy=" + v.fy
	if !(v.l.controls && r.ScheduleURL != "") && r.LeaveURL == "" {
		// View alone, as its own button: a plain cell to the feed.
		return &screensv1.PageCell{Text: "View"}
	}
	item := func(key, label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href, Drawer: true}
	}
	cell := &screensv1.PageCell{Actions: []*screensv1.PageAction{item("menu", "View", view)}}
	if v.l.controls {
		if r.ScheduleURL != "" {
			cell.Actions = append(cell.Actions, item("menu", "Schedule", r.ScheduleURL), item("menu", "Assign", r.PartnerURL))
		} else {
			cell.Text = pausedNote
		}
	}
	if r.LeaveURL != "" {
		cell.Actions = append(cell.Actions, item("danger", "Withdraw from project", r.LeaveURL))
	}
	return cell
}

// details is the opened row: who added the school, the verdict, and each
// focus intervention's readings.
func details(r schoolRow) []*screensv1.PageFact {
	out := []*screensv1.PageFact{
		{Label: "Added by", Value: r.AddedBy},
		{Label: "Improvement", Value: r.ImpactLabel},
	}
	for _, f := range r.Focus {
		label := f.Abbreviation
		if label == "" {
			label = f.Label
		}
		value := "–"
		if f.Baseline != nil {
			value = floatStr(*f.Baseline)
		}
		if f.Latest != nil {
			value += " → " + floatStr(*f.Latest)
			if c := f.change(); c != nil {
				sign := ""
				if *c > 0 {
					sign = "+"
				}
				value += " (" + sign + floatStr(*c) + ")"
			}
		}
		out = append(out, &screensv1.PageFact{Label: label, Value: value})
	}
	return out
}

// sortedFold is sorted(values, key=str.casefold).
func sortedFold(values map[string]bool) []string {
	out := make([]string, 0, len(values))
	for value := range values {
		out = append(out, value)
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := strings.ToLower(out[i]), strings.ToLower(out[j])
		if a != b {
			return a < b
		}
		return out[i] < out[j]
	})
	return out
}
