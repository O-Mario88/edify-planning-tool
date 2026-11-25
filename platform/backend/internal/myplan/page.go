package myplan

import (
	"fmt"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// stripFigures is the Plan progress strip's length (services.MY_PLAN_TILES).
const stripFigures = 8

// header is the page header (pages/my_plan/index.html): its Export opens
// the Export options drawer with the page's own query.
func header(request Query) *screensv1.PageHeader {
	return &screensv1.PageHeader{
		Eyebrow:     "My Work",
		Title:       "My Plan",
		Description: "Everything you have planned, oldest first. Filter by fiscal year, quarter or month.",
		Actions: []*screensv1.PageAction{{
			Key: "export", Label: "Export", Enabled: true, Drawer: true,
			Href: "/my-plan/export-drawer" + request.String(request),
		}},
	}
}

// Choices is what the page's other selects offer: every district and every
// active member of staff, by name.
type Choices struct {
	Districts, Staff []option
}

// filters is the filter form (partials/my_plan/filters.html): the period's
// three selects, then district, staff, activity type and status, each read
// as sent; and what the form was drawn with.
func filters(p Period, years []string, c Choices, query Query) *screensv1.PageBlock {
	get := func(key string) string {
		for i, k := range query.keys {
			if k == key {
				return query.values[i]
			}
		}
		return ""
	}
	sent := func(key string) func(string) bool {
		value := get(key)
		return func(v string) bool { return v == value }
	}
	allOr := func(key string) func(string) bool {
		value := get(key)
		return func(v string) bool {
			if value == "" || value == "all" {
				return v == "all"
			}
			return v == value
		}
	}
	districts := append([]option{{"all", "All districts"}}, c.Districts...)
	staff := append([]option{{"all", "All staff"}}, c.Staff...)
	types := []option{
		{"all", "All types"}, {"school_visit", "School Visit"},
		{"cluster_training", "Cluster Training"}, {"cluster_meeting", "Cluster Meeting"},
	}
	statuses := []option{
		{"all", "All statuses"}, {"scheduled", "Scheduled"}, {"upcoming", "Planned (not started)"},
		{"under_way", "In progress"}, {"overdue", "Overdue (not started)"}, {"completed", "Completed"},
		{"submitted", "Submitted"}, {"returned_for_correction", "Returned"},
	}
	all := append(p.PeriodFilters(years),
		selectFilter("district", "District", districts, sent("district")),
		selectFilter("staff", "Staff member", staff, sent("staff")),
		selectFilter("activity_type", "Activity type", types, allOr("activity_type")),
		selectFilter("status", "Status", statuses, allOr("status")),
	)
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: all, Hidden: p.Hidden(),
	}}}
}

// PlanCounts are the figures of the strip and the period breakdown.
type PlanCounts struct {
	Week, Month, Quarter, FY         int
	Visits, CoreVisits, ClientVisits int
	Trainings, Meetings              int
	Completed, Total                 int
	// Outreach is the period's donor, story, social and invitation visits
	// (and SSA Support), planned beside the target and not counted toward it.
	Outreach int
}

// comma is |intcomma of a whole number.
func comma(n int) string {
	digits := strconv.Itoa(n)
	sign := ""
	if strings.HasPrefix(digits, "-") {
		sign, digits = "-", digits[1:]
	}
	for i := len(digits) - 3; i > 0; i -= 3 {
		digits = digits[:i] + "," + digits[i:]
	}
	return sign + digits
}

// visitsLine is the line under the visits figure for a reader without a
// visit target: their counted visits at Core schools and at the others.
func visitsLine(c PlanCounts) string {
	return comma(c.CoreVisits) + " Core, " + comma(c.ClientVisits) + " Client"
}

// progressStrip is Plan progress (partials/my_plan/kpi_cards.html) for a
// reader without a visit target. A plan with nothing in the period has no
// completed share ("No data").
func progressStrip(c PlanCounts, target int) *screensv1.PageBlock {
	values := []string{
		comma(c.Week), comma(c.Month), comma(c.Quarter), comma(c.FY),
		comma(c.Visits), comma(c.Trainings), comma(c.Meetings), share(c.Completed, c.Total),
	}
	strip := &screensv1.PageStrip{Title: "Plan progress"}
	for i, label := range rules.Strip.Labels {
		m := &screensv1.PageMetric{Label: label, Value: values[i], Href: rules.Strip.Drilldown}
		if rules.Strip.Keys[i] == "my_plan_visits_scheduled_period" {
			m.Helper = visitsLine(c)
			if target > 0 {
				targetVisitsTile(m, target, c)
			}
		}
		strip.Metrics = append(strip.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// breakdown is Plan Breakdown by Period (partials/my_plan/period_breakdown.html).
func breakdown(c PlanCounts) *screensv1.PageBlock {
	strip := &screensv1.PageStrip{Title: "Plan Breakdown by Period", Subtitle: "All activity types combined"}
	for _, f := range []struct {
		label string
		n     int
	}{{"This Week", c.Week}, {"This Month", c.Month}, {"This Quarter", c.Quarter}, {"This FY", c.FY}} {
		strip.Metrics = append(strip.Metrics, &screensv1.PageMetric{Label: f.label, Value: comma(f.n) + " activities"})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// PlanTable names one of the plan's four always-drawn tables and its empty
// state (partials/my_plan/school_visits.html, cluster_trainings.html,
// group_trainings.html, cluster_meetings.html).
type PlanTable struct{ Title, Empty string }

// PlanTables are the four tables every My Plan draws, in the page's order.
var PlanTables = []PlanTable{
	{"School Visits Planned for", "No school visits planned for this period."},
	{"Trainings Planned for", "No trainings planned for this period."},
	{"Group Trainings Planned for", "No group trainings planned for this period."},
	{"Cluster Meetings Planned for", "No cluster meetings planned for this period."},
}

// emptyTable is a table of the plan with nothing in it: its title, a count
// of 0, and the empty state's door to Planning.
func emptyTable(t PlanTable, p Period) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title: t.Title + " " + p.Words(), Count: "0", EmptyMessage: t.Empty,
		EmptyAction: &screensv1.PageAction{Key: "empty", Label: "Open Planning", Enabled: true, Href: "/planning"},
	}}}
}

// activityBar is the bar for ticked activities
// (partials/activities/selection_bar.html).
func activityBar() *screensv1.PageSelection {
	return &screensv1.PageSelection{Noun: "activities selected", Actions: []*screensv1.PageSelectionAction{
		{Label: "Reschedule", Href: "/activity-selection/reschedule", Param: "ids", Joined: true},
		{Label: "Cancel", Href: "/activity-selection/cancel", Param: "ids", Joined: true},
	}}
}

// pastDueNote is the line under Plan progress when planned work is past its
// day and not delivered (partials/my_plan/kpi_cards.html): a warning note
// whose words the feed reads, with its link, What needs you now on the
// Dashboard.
func pastDueNote(n int) *screensv1.PageBlock {
	words := [3]string{"activities are", "their", "They are"}
	if n == 1 {
		words = [3]string{"activity is", "its", "It is"}
	}
	text := fmt.Sprintf("%d planned %s past %s date and not yet completed. %s counted above and listed under "+
		"What needs you now on the Dashboard, not in the tables below.", n, words[0], words[1], words[2])
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: text}, Tone: "warning",
			TextLinks: []*screensv1.PageLink{{Text: "What needs you now", Href: "/dashboard"}}}},
	}}}
}

// pageParts are what My Plan is drawn from.
type pageParts struct {
	period  Period
	years   []string
	choices Choices
	request Query
	plan    Plan
	filters Filters
	// target is the reader's visit target (0 for none); planned their
	// counted visits of the year. readiness is populated when OwnReadiness
	// is wired in.
	target, planned int
	readiness       *OwnReadiness
	tables          PlanTablesResult
	// summary is the reader's own My Training Summary.
	summary []TrainingSummaryRow
	// clusters is Cluster Planning Status (apps.clusters.planning_status).
	clusters []clusterPlanRow
}

// emptyPage is My Plan for a reader with no target whose tables list
// nothing: the plan counted, the tables empty.
func emptyPage(p Period, years []string, c Choices, request Query, plan Plan, f Filters, target int) *screensv1.GetPageResponse {
	return planPage(pageParts{period: p, years: years, choices: c, request: request, plan: plan, filters: f, target: target})
}

// planPage is My Plan: the plan counted, the planner's Planned and
// remaining, and the tables.
func planPage(parts pageParts) *screensv1.GetPageResponse {
	p, request, f := parts.period, parts.request, parts.filters
	form := filters(p, parts.years, parts.choices, request)
	status := f.Status
	if parts.tables.overwritten {
		// The Status select shows the Core slot's status the loop left (25.3).
		status = parts.tables.statusShown
		for _, sel := range form.GetFilters().GetFilters() {
			if sel.GetName() == "status" {
				sel.Value = status
			}
		}
	}
	blocks := []*screensv1.PageBlock{p.Tabs(request), form}
	t := parts.tables
	if len(t.dayOff) > 0 {
		blocks = append(blocks, dayOffCard(t.dayOff))
	}
	if len(t.returned) > 0 {
		blocks = append(blocks, returnedCard(t.returned))
	}
	if len(t.waiting) > 0 {
		blocks = append(blocks, waitingCard(t.waiting))
	}
	if len(t.finance) > 0 {
		blocks = append(blocks, financeCard(t.finance))
	}
	blocks = append(blocks, progressStrip(parts.plan.Counts, parts.target))
	if parts.plan.PastDue > 0 && status != "overdue" && status != "under_way" {
		blocks = append(blocks, pastDueNote(parts.plan.PastDue))
	}
	// A planner's own Planned and remaining, loaded once the page is open
	// (readiness_panel.html), and the schools behind a figure when asked.
	if parts.readiness != nil {
		blocks = append(blocks, fullReadinessTable(parts.readiness, p.FY, request))
		if key := readinessList(request); key != "" {
			blocks = append(blocks, emptyReadinessList(key))
		}
	} else if parts.target > 0 {
		blocks = append(blocks, readinessTable(parts.target, parts.planned, p.FY, request))
		if key := readinessList(request); key != "" {
			blocks = append(blocks, emptyReadinessList(key))
		}
	}
	if len(parts.summary) > 0 {
		blocks = append(blocks, summaryBlocks(parts.summary, p.FY)...)
	}
	blocks = append(blocks, planTablesBlocks(parts.tables, p, parts.clusters)...)
	blocks = append(blocks, breakdown(parts.plan.Counts))
	return &screensv1.GetPageResponse{Header: header(request), Blocks: blocks, Selection: activityBar(), WebPath: Path}
}
