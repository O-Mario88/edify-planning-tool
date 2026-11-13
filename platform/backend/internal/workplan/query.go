package workplan

import (
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// fyMonthOrder is FY_MONTH_ORDER: October to September.
var fyMonthOrder = []int{10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9}

// quarterMonths is QUARTER_MONTHS, in its order.
var quarterMonths = map[string][]int{
	"Q1": {10, 11, 12}, "Q2": {1, 2, 3}, "Q3": {4, 5, 6}, "Q4": {7, 8, 9},
}

var quarterOrder = []string{"Q1", "Q2", "Q3", "Q4"}

var monthNames = []string{"", "January", "February", "March", "April", "May", "June",
	"July", "August", "September", "October", "November", "December"}

// pyStrip is str.strip(): Unicode whitespace off both ends.
func pyStrip(s string) string { return closedschools.PyStrip(s) }

// monthYear is _month_year: the calendar year of a month in an Oct–Sep FY.
func monthYear(fy, month int) int {
	if month >= 10 {
		return fy - 1
	}
	return fy
}

func monthLabel(fy, month int) string {
	return monthNames[month] + " " + strconv.Itoa(monthYear(fy, month))
}

// operationalFY is get_operational_fy of a calendar day.
func operationalFY(day time.Time) string {
	if day.Month() >= time.October {
		return strconv.Itoa(day.Year() + 1)
	}
	return strconv.Itoa(day.Year())
}

// currentQuarter is get_quarter_for_date of a calendar day.
func currentQuarter(day time.Time) string {
	switch m := int(day.Month()); {
	case m >= 10:
		return "Q1"
	case m <= 3:
		return "Q2"
	case m <= 6:
		return "Q3"
	}
	return "Q4"
}

// fyOptions is apps.core.fy.fy_options.
func fyOptions(day time.Time) []string {
	current, _ := strconv.Atoi(operationalFY(day))
	top := max(current+1, 2027)
	out := []string{}
	for y := 2025; y <= top; y++ {
		out = append(out, strconv.Itoa(y))
	}
	return out
}

// state is what build_work_plan_context reads from the request.
type state struct {
	fy, operational string
	fyInt           int
	view            string
	month           int    // the period of the month view
	quarter         string // the period of the quarter view
	status          string
	responsible     string
	project         string
	activityType    string
	executor        string
	flag            string
	isPL            bool
	role            string
	scope           string
	today           time.Time
}

// period is str(period) as the page carries it.
func (s state) period() string {
	switch s.view {
	case "month":
		return strconv.Itoa(s.month)
	case "quarter":
		return s.quarter
	}
	return ""
}

func (s state) windowMonths() []int {
	switch s.view {
	case "fy":
		return fyMonthOrder
	case "quarter":
		return quarterMonths[s.quarter]
	}
	return []int{s.month}
}

// windowBounds is _window_bounds: the first day of the window's first month
// to the last day of its last.
func (s state) windowBounds() (time.Time, time.Time) {
	months := s.windowMonths()
	first, last := months[0], months[len(months)-1]
	start := time.Date(monthYear(s.fyInt, first), time.Month(first), 1, 0, 0, 0, 0, time.UTC)
	endYear := monthYear(s.fyInt, last)
	end := time.Date(endYear, time.Month(last)+1, 0, 0, 0, 0, 0, time.UTC)
	return start, end
}

// periodLabel is the page's period_label.
func (s state) periodLabel() string {
	switch s.view {
	case "month":
		return monthLabel(s.fyInt, s.month)
	case "quarter":
		return s.quarter + " FY" + s.fy
	}
	return "FY" + s.fy
}

// readState is the top of build_work_plan_context: the year (the planning
// year once it is open, else the running one), the view and its period,
// the filters, and a Program Lead's audience.
func readState(get func(string) string, role, nextOpen string, today time.Time) state {
	s := state{today: today, operational: operationalFY(today)}
	options := fyOptions(today)
	defaultFY := nextOpen
	if defaultFY == "" {
		defaultFY = s.operational
	}
	if !in(options, defaultFY) {
		defaultFY = s.operational
	}
	s.fy = get("fy")
	if s.fy == "" {
		s.fy = defaultFY
	}
	if !in(options, s.fy) {
		s.fy = defaultFY
	}
	s.fyInt, _ = strconv.Atoi(s.fy)

	s.view = get("view")
	if s.view != "month" && s.view != "quarter" && s.view != "fy" {
		s.view = "month"
	}
	fyPrev := get("fy_prev")
	fyChanged := fyPrev != "" && s.fy != fyPrev
	switch s.view {
	case "month":
		raw := get("period")
		if raw == "" {
			raw = "0"
		}
		n, ok := closedschools.PyInt(raw)
		if !ok {
			n = 0
		}
		if fyChanged || n < 1 || n > 12 {
			n = 10
			if s.fy == s.operational {
				n = int(today.Month())
			}
		}
		s.month = n
	case "quarter":
		q := get("period")
		if _, ok := quarterMonths[q]; fyChanged || !ok {
			q = "Q1"
			if s.fy == s.operational {
				q = currentQuarter(today)
			}
		}
		s.quarter = q
	}
	s.status = pyStrip(get("status"))
	s.responsible = pyStrip(get("responsible"))
	s.project = pyStrip(get("project"))
	s.activityType = pyStrip(get("activity_type"))
	s.executor = pyStrip(get("executor"))
	s.flag = pyStrip(get("flag"))
	if _, ok := rules.FlagLabels[s.flag]; !ok {
		s.flag = ""
	}
	s.role = role
	s.isPL = role == roleProgramLead
	s.scope = "team"
	if get("scope") == "own" || !s.isPL {
		s.scope = "own"
	}
	if !valueIn(rules.Statuses, s.status) {
		s.status = ""
	}
	return s
}

// kv is one key of a query in the order urlencode writes it.
type kv struct{ key, value string }

// base is query_state: the page's own query, in its order.
func (s state) base() []kv {
	scope := ""
	if s.isPL {
		scope = s.scope
	}
	return []kv{
		{"fy", s.fy}, {"view", s.view}, {"period", s.period()}, {"status", s.status},
		{"responsible", s.responsible}, {"project", s.project}, {"activity_type", s.activityType},
		{"executor", s.executor}, {"flag", s.flag}, {"scope", scope},
	}
}

// link is _query_string(base, **overrides): the base without its empty
// keys, each override set in its place or added last ("" removes it).
func link(base []kv, overrides ...kv) string {
	merged := []kv{}
	for _, p := range base {
		if p.value != "" {
			merged = append(merged, p)
		}
	}
	for _, o := range overrides {
		at := -1
		for i, p := range merged {
			if p.key == o.key {
				at = i
			}
		}
		switch {
		case o.value == "" && at >= 0:
			merged = append(merged[:at:at], merged[at+1:]...)
		case o.value == "":
		case at >= 0:
			merged[at].value = o.value
		default:
			merged = append(merged, o)
		}
	}
	if len(merged) == 0 {
		return "/work-plan"
	}
	parts := make([]string, len(merged))
	for i, p := range merged {
		parts[i] = url.QueryEscape(p.key) + "=" + url.QueryEscape(p.value)
	}
	return "/work-plan?" + strings.Join(parts, "&")
}

// requestQuery is request.GET.urlencode as the feed hands the page its
// query: every key it passes, in key order.
func requestQuery(query url.Values) string {
	keys := make([]string, 0, len(query))
	for key := range query {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	parts := []string{}
	for _, key := range keys {
		for _, value := range query[key] {
			parts = append(parts, url.QueryEscape(key)+"="+url.QueryEscape(value))
		}
	}
	return strings.Join(parts, "&")
}
