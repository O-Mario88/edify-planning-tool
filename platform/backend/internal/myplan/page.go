package myplan

import (
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

// progressStrip is Plan progress (partials/my_plan/kpi_cards.html) for a
// reader without a visit target: their counted visits are written "n Core,
// n Client" under the visits figure. A reader with nothing planned has no
// completed share ("No data").
func progressStrip(c PlanCounts) *screensv1.PageBlock {
	values := []string{
		comma(c.Week), comma(c.Month), comma(c.Quarter), comma(c.FY),
		comma(c.Visits), comma(c.Trainings), comma(c.Meetings), rules.Strip.NoData,
	}
	strip := &screensv1.PageStrip{Title: "Plan progress"}
	for i, label := range rules.Strip.Labels {
		m := &screensv1.PageMetric{Label: label, Value: values[i], Href: rules.Strip.Drilldown}
		if rules.Strip.Keys[i] == "my_plan_visits_scheduled_period" {
			m.Helper = comma(c.CoreVisits) + " Core, " + comma(c.ClientVisits) + " Client"
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

// emptyPage is My Plan for a reader with nothing planned and no target.
func emptyPage(p Period, years []string, c Choices, request Query) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{p.Tabs(request), filters(p, years, c, request), progressStrip(PlanCounts{})}
	for _, t := range PlanTables {
		blocks = append(blocks, emptyTable(t, p))
	}
	blocks = append(blocks, breakdown(PlanCounts{}))
	return &screensv1.GetPageResponse{Header: header(request), Blocks: blocks, Selection: activityBar(), WebPath: Path}
}
