package projectmyplan

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
)

// row is one listed piece of work as _row writes it.
type row struct {
	w                                         work
	id, schoolCode, school, district, project string
	focus, partner, participants, status      string
	evidence, purpose                         string
	planned, completed                        *time.Time
	action                                    todos.NextAction
	readonly                                  bool
}

// statusLabel is get_activity_status_label_and_class's words.
func statusLabel(w work, today time.Time) string {
	switch w.status {
	case "completed", "closed":
		return rules.CompleteLabel
	case "awaiting_owner_approval":
		return "Awaiting owner approval"
	case "submitted_to_pl", "awaiting_ia_verification", "ia_verified", "accountant_confirmed":
		if w.salesforce == "" {
			return "Activity ID Missing"
		}
		return rules.CompleteLabel
	case "returned", "returned_by_pl", "returned_by_ia":
		return "Returned for Correction"
	}
	planned := w.planned
	switch {
	case planned != nil && dayOf(*planned).Equal(today):
		return "Due Today"
	case w.reschedules > 0:
		return "Rescheduled"
	case planned != nil && dayOf(*planned).After(today) && !dayOf(*planned).After(today.AddDate(0, 0, 7)):
		return "This Week"
	}
	return "Scheduled"
}

func (pg *page) assemble(p auth.Principal, works []work, next map[string]todos.NextAction, partnerNames, projectNames map[string]string) {
	own := map[string]bool{p.UserID: true, p.StaffProfileID: true}
	for _, w := range works {
		r := row{w: w, id: w.id, status: statusLabel(w, pg.today)}
		r.action = next[w.id]
		if !(w.delivery == "staff" && own[w.staff]) {
			r.action = todos.NextAction{Text: "View details", Action: "view", URL: "/my-plan/" + w.id, Description: "Monitoring only"}
		}
		r.readonly = w.delivery == "partner" || !(w.delivery == "staff" && own[w.staff])
		switch {
		case w.hasSchool:
			r.schoolCode, r.school = w.schoolCode, w.school
		case w.hasCluster:
			r.school = w.cluster
		default:
			r.school = "Unassigned"
		}
		switch {
		case w.hasSchool && w.schoolDistrict != "":
			r.district = w.schoolDistrict
		case w.hasCluster && w.clusterDistrict != "":
			r.district = w.clusterDistrict
		default:
			r.district = "—"
		}
		if r.project = projectNames[w.projectID]; r.project == "" {
			r.project = "—"
		}
		r.planned = w.plannedBefore
		if r.planned == nil {
			r.planned = w.planned
		}
		if in(rules.OfficerCompletedStatuses, w.status) {
			r.completed = w.delivered
		}
		if r.purpose = w.purpose; r.purpose == "" {
			r.purpose = label(rules.ActivityTypes, w.kind)
		}
		if r.focus = rules.Interventions[w.focus]; r.focus == "" {
			r.focus = "General support"
		}
		if r.partner = partnerNames[w.partnerID]; r.partner == "" {
			r.partner = "—"
		}
		r.participants = "—"
		if n := w.teachers + w.leaders + w.others; n != 0 {
			r.participants = strconv.Itoa(n)
		}
		if r.evidence = evidenceLabels[w.evidence]; r.evidence == "" {
			r.evidence = label(rules.EvidenceStatuses, w.evidence)
		}
		pg.all = append(pg.all, r)
		switch {
		case w.delivery == "partner":
			pg.partnerWork = append(pg.partnerWork, r)
		case w.delivery == "staff" && in(rules.VisitTypes, w.kind):
			pg.visits = append(pg.visits, r)
		case w.delivery == "staff" && in(rules.TrainingTypes, w.kind):
			pg.trainings = append(pg.trainings, r)
		case w.delivery == "staff" && in(rules.MeetingTypes, w.kind):
			pg.meetings = append(pg.meetings, r)
		}
		if in(rules.DeliveredStatuses, w.status) {
			pg.completed++
		}
		if w.lines > 0 {
			pg.budgeted++
		}
		awaitingEvidence := (w.status == "completed" || w.status == "evidence_uploaded") && w.evidence != "accepted"
		if awaitingEvidence {
			pg.evidencePending++
		}
		if w.status == "awaiting_ia_verification" {
			pg.iaPending++
		}
		late := w.planned != nil && dayOf(*w.planned).Before(pg.today) && in([]string{"scheduled", "rescheduled", "in_progress"}, w.status)
		if late {
			pg.overdue++
		}
		if w.planned != nil && dayOf(*w.planned).Equal(pg.today) && len(pg.upcoming) < 4 {
			pg.upcoming = append(pg.upcoming, r)
		}
		if len(pg.attention) < 5 {
			issue, tone := "", ""
			switch {
			case in(rules.ReturnedStates, w.status):
				issue, tone = "Returned for correction", "danger"
			case w.reschedules > 0:
				issue, tone = fmt.Sprintf("Rescheduled %d time(s)", w.reschedules), "danger"
			case awaitingEvidence:
				issue, tone = "Evidence needs attention", "warning"
			case w.delivery == "partner" && w.status == "assigned_to_partner":
				issue, tone = "Partner confirmation pending", "warning"
			case w.status == "awaiting_ia_verification":
				issue, tone = "IA review pending", "info"
			case late:
				issue, tone = "Activity is overdue", "danger"
			}
			if issue != "" {
				pg.attention = append(pg.attention, attention{issue: issue, tone: tone, title: r.school, url: "/my-plan/" + w.id})
			}
		}
	}
	pg.total = len(works)
}

// truncate is the truncatechars filter: n-1 characters and an ellipsis.
func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	r := []rune(s)
	return string(r[:n-1]) + "…"
}

func plainDate(t *time.Time) string { return t.Format("Jan 2, Mon") }

func filter(name, lbl, caption, value string, options [][2]string) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: lbl, Caption: caption}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if o[0] == value {
			f.Value = value
		}
	}
	return f
}

func (pg *page) filters() *screensv1.PageBlock {
	years := [][2]string{}
	for _, y := range pg.fyOptions {
		years = append(years, [2]string{y, "FY " + y})
	}
	months := [][2]string{}
	for _, m := range pg.months {
		months = append(months, [2]string{strconv.Itoa(m), time.Month(m).String()})
	}
	weeks := [][2]string{}
	for _, w := range pg.weeks {
		weeks = append(weeks, [2]string{w.value, w.label})
	}
	projects := [][2]string{{"", "All projects"}}
	for _, p := range pg.projects {
		projects = append(projects, [2]string{p.id, p.name})
	}
	statuses := append([][2]string{{"", "All active statuses"}}, statusOptions...)
	districts := [][2]string{{"", "All districts"}}
	for _, d := range pg.districts {
		districts = append(districts, [2]string{d.value, d.label})
	}
	partners := [][2]string{{"", "All partners"}}
	for _, p := range pg.partners {
		partners = append(partners, [2]string{p.value, p.label})
	}
	kinds := [][2]string{{"", "All types"}}
	for _, k := range pg.kinds {
		l, ok := rules.ActivityTypes[k]
		if !ok {
			l = pyTitle(strings.ReplaceAll(k, "_", " "))
		}
		kinds = append(kinds, [2]string{k, l})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			filter("fy", "Fiscal year", "Fiscal Year", pg.f.fy, years),
			filter("quarter", "Quarter", "", pg.f.quarter, [][2]string{{"Q1", "Q1"}, {"Q2", "Q2"}, {"Q3", "Q3"}, {"Q4", "Q4"}}),
			filter("month", "Month", "", pg.f.month, months),
			filter("week", "Week", "", pg.f.week, weeks),
			filter("project", "Project", "", pg.f.project, projects),
			filter("status", "Status", "", pg.f.status, statuses),
			filter("district", "District", "", pg.f.district, districts),
			filter("partner", "Partner", "", pg.f.partner, partners),
			filter("activity_type", "Activity type", "Activity Type", pg.f.activityType, kinds),
		},
		Hidden: map[string]string{"period": pg.f.period},
	}}}
}

// pyTitle is Python's str.title() over plain words.
func pyTitle(s string) string {
	out := []rune{}
	start := true
	for _, c := range s {
		if start {
			out = append(out, []rune(strings.ToUpper(string(c)))...)
		} else {
			out = append(out, []rune(strings.ToLower(string(c)))...)
		}
		start = !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z')
	}
	return string(out)
}

func (pg *page) strip() *screensv1.PageBlock {
	completion := 0
	if pg.total > 0 {
		completion = int(math.RoundToEven(float64(pg.completed) / float64(pg.total) * 100))
	}
	values := []string{strconv.Itoa(pg.breakdown[0]), strconv.Itoa(pg.breakdown[1]), strconv.Itoa(pg.breakdown[2]),
		strconv.Itoa(pg.breakdown[3]), strconv.Itoa(len(pg.visits)), strconv.Itoa(len(pg.partnerWork)),
		strconv.Itoa(len(pg.trainings)), fmt.Sprintf("%d%%", completion)}
	helpers := []string{"activities", "activities", "activities", "activities", "visits in period", "monitoring only",
		"trainings in period", "workflow complete"}
	return fundworkspace.Strip("Special project plan context", rules.MetricLabels[:8], values, helpers)
}

var kindColumns = map[string][]string{
	"visits":    {"School ID", "School / Cluster", "District", "Project", "Planned date", "Completed date", "Purpose", "Status", "Action"},
	"trainings": {"School ID", "School / Cluster", "District", "Project", "Focus", "Planned date", "Completed date", "Purpose", "Participants", "Status", "Action"},
	"meetings":  {"School ID", "School / Cluster", "District", "Project", "Focus", "Planned date", "Completed date", "Purpose", "Status", "Action"},
	"partners":  {"School ID", "School / Cluster", "District", "Project", "Focus", "Planned date", "Completed date", "Purpose", "Partner", "Evidence", "Status", "Action"},
}

func cell(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: t} }

func table(kind string, rows []row) *screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, c := range kindColumns[kind] {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, r := range rows {
		code := r.schoolCode
		if code == "" {
			code = "—"
		}
		planned := "Not scheduled"
		if r.planned != nil {
			planned = plainDate(r.planned)
		}
		completed := "—"
		if r.completed != nil {
			completed = plainDate(r.completed)
		}
		cells := []*screensv1.PageCell{cell(code), {Text: r.school, Strong: true}, cell(r.district), cell(r.project)}
		if kind != "visits" {
			cells = append(cells, cell(r.focus))
		}
		cells = append(cells, cell(planned), cell(completed), cell(truncate(r.purpose, 52)))
		switch kind {
		case "partners":
			cells = append(cells, cell(r.partner), cell(r.evidence))
		case "trainings":
			cells = append(cells, cell(r.participants))
		}
		cells = append(cells, cell(r.status), &screensv1.PageCell{Text: r.action.Text, Href: r.action.URL})
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

type card struct {
	title, kind, empty string
	rows               []row
}

func (pg *page) cards() []card {
	cap25 := func(r []row) []row { return r[:min(len(r), 25)] }
	return []card{
		{fmt.Sprintf("Project School Visits Planned %d", len(cap25(pg.visits))), "visits", "No project school visits match this period.", cap25(pg.visits)},
		{fmt.Sprintf("Project Trainings Planned %d", len(cap25(pg.trainings))), "trainings", "No project trainings match this period.", cap25(pg.trainings)},
		{fmt.Sprintf("Project Cluster Meetings Planned %d", len(cap25(pg.meetings))), "meetings", "No project cluster meetings match this period.", cap25(pg.meetings)},
		{fmt.Sprintf("Partner-Planned Project Activities %dRead only", len(cap25(pg.partnerWork))), "partners", "No partner-planned project activities match this period.", cap25(pg.partnerWork)},
	}
}

func text(t string) *screensv1.PagePanelItem    { return fundworkspace.Text(t) }
func heading(t string) *screensv1.PagePanelItem { return fundworkspace.Heading(t) }

// aside is the insight column as the feed reads it: one panel titled by its
// first card, the later cards' titles as headings.
func (pg *page) aside() (string, []*screensv1.PagePanelItem) {
	type section struct {
		title string
		items []*screensv1.PagePanelItem
	}
	sections := []section{}
	if len(pg.upcoming) > 0 {
		items := []*screensv1.PagePanelItem{text(strconv.Itoa(len(pg.upcoming)))}
		for _, r := range pg.upcoming {
			items = append(items, text(r.school), text(r.project), text(truncate(r.purpose, 48)),
				fundworkspace.Links(&screensv1.PageLink{Text: "View", Href: "/my-plan/" + r.id, Drawer: true}))
		}
		sections = append(sections, section{"Upcoming Today", items})
	}
	if len(pg.attention) > 0 {
		links := []*screensv1.PageLink{}
		for _, a := range pg.attention {
			links = append(links, &screensv1.PageLink{Text: "!", Href: a.url, Caption: a.issue + a.title + " · →", Drawer: true})
		}
		sections = append(sections, section{"Attention Needed", []*screensv1.PagePanelItem{text(strconv.Itoa(len(pg.attention))), fundworkspace.Links(links...)}})
	}
	total := strconv.Itoa(pg.total)
	workflow := []struct {
		label, value string
		ok           bool
	}{
		{rules.MetricLabels[8], fmt.Sprintf("%d / %s", pg.budgeted, total), true},
		{rules.MetricLabels[9], fmt.Sprintf("%d / %s", pg.advanced, total), pg.advanced == pg.total && pg.total > 0},
		{rules.MetricLabels[10], fmt.Sprintf("%d / %s", pg.evidencePending, total), pg.evidencePending == 0},
		{rules.MetricLabels[11], fmt.Sprintf("%d / %s", pg.iaPending, total), pg.iaPending == 0},
	}
	links := []*screensv1.PageLink{}
	for _, item := range workflow {
		mark := "!"
		if item.ok {
			mark = ""
		}
		links = append(links, &screensv1.PageLink{Text: mark + item.label + item.value})
	}
	sections = append(sections, section{"Budget & Workflow Status", []*screensv1.PagePanelItem{fundworkspace.Links(links...)}})
	title, message, actionText, url, drawer := "Review the project plan", "There are no activities in the selected period.", "Open project planning", "/projects/planning", false
	if pg.total > 0 {
		message = "No workflow action is due in this period."
	}
	for _, r := range pg.all {
		if !r.readonly && r.action.Action != "view" {
			title, message, actionText, url, drawer = r.action.Text, r.action.Description, r.action.Text, r.action.URL, true
			break
		}
	}
	next := []*screensv1.PagePanelItem{text("Next step"), heading(title), text(message),
		fundworkspace.Links(&screensv1.PageLink{Text: actionText + " →", Href: url, Drawer: drawer})}
	items := []*screensv1.PagePanelItem{}
	for i, s := range sections {
		if i > 0 {
			items = append(items, heading(s.title))
		}
		items = append(items, s.items...)
	}
	return sections[0].title, append(items, next...)
}

// workspaceNav is partials/projects/workspace_nav.html: the chosen project's
// own pages, Activities being this one.
func (pg *page) workspaceNav() *screensv1.PageBlock {
	name := ""
	for _, p := range pg.projects {
		if p.id == pg.f.project {
			name = p.name
		}
	}
	id := pg.f.project
	t := &screensv1.PageLinkTabs{Label: name, Scrolls: true}
	for _, tab := range [][2]string{
		{"Overview", "/projects/" + id}, {"Schools", "/projects/" + id + "#participating-schools"},
		{"Plan", "/projects/planning?project=" + id}, {"Activities", "/projects/my-plan?project=" + id},
		{"Partners", "/projects/planning?project=" + id + "&partner_type=partner"}, {"Budget", "/projects/" + id + "#budget-execution"},
		{"Impact", "/projects/analytics?project=" + id}, {"Issues", "/projects/my-plan?project=" + id + "#project-attention"},
	} {
		t.Tabs = append(t.Tabs, &screensv1.PageLinkTab{Label: tab[0], Href: tab[1], Active: tab[0] == "Activities"})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: t}}
}

func (pg *page) blocks() []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{}
	if pg.f.project != "" {
		out = append(out, pg.workspaceNav())
	}
	out = append(out, pg.filters(), pg.strip(),
		fundworkspace.Panel("", text("Week"), text("Month"), text("Quarter"), text("FY"), text("Showing plans for "+pg.periodLabel)))
	cards := pg.cards()
	asideTitle, asideItems := pg.aside()
	anyRows := false
	for _, c := range cards {
		anyRows = anyRows || len(c.rows) > 0
	}
	if anyRows {
		for _, c := range cards {
			if len(c.rows) == 0 {
				out = append(out, fundworkspace.Panel(c.title, text(c.empty)))
				continue
			}
			out = append(out, fundworkspace.Panel(c.title), table(c.kind, c.rows))
		}
		out = append(out, fundworkspace.Panel(asideTitle, asideItems...))
	} else {
		// With no table anywhere the feed reads the whole layout as one
		// card: the first list's title, the others' as headings.
		items := []*screensv1.PagePanelItem{text(cards[0].empty)}
		for _, c := range cards[1:] {
			items = append(items, heading(c.title), text(c.empty))
		}
		items = append(items, heading(asideTitle))
		out = append(out, fundworkspace.Panel(cards[0].title, append(items, asideItems...)...))
	}
	records := "s"
	if pg.total == 1 {
		records = ""
	}
	out = append(out, fundworkspace.Panel("", heading(fmt.Sprintf("Data details · %d records", pg.total)),
		text(fmt.Sprintf("%d scoped record%s · %s evidence · Decision support; source workflow records remain authoritative.",
			pg.total, records, strings.ToLower(quality(pg.total))))))
	return out
}
