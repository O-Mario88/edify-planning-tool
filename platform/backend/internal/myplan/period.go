package myplan

import (
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// kampala is the platform's day (date.today() under TIME_ZONE): East Africa
// Time, three hours ahead of UTC all year.
var kampala = time.FixedZone("EAT", 3*60*60)

// Period is My Plan's period filters as get_frontend_context reads them: a
// fiscal year holds quarters, a quarter holds months, and widening one (the
// form sends what it was drawn with as fy_prev and quarter_prev) clears what
// it contains. It is shared by every page that lists My Plan's tables.
type Period struct {
	// FY is the year as sent (not stripped), else the year of today.
	FY string
	// Quarter is the quarter chosen, as sent, or "" when none is.
	Quarter string
	// Month is the month chosen, or a quarter's first month; HasMonth says
	// whether there is one.
	Month    int
	HasMonth bool
	// Kind is the slice the tables show: the ?period= asked for (stripped),
	// else "month" with a month chosen, else "fy".
	Kind string
	// Asked is the ?period= asked for, stripped; "" when none was.
	Asked string
	// Week is the week of the month the "week" slice reads (1 to 5).
	Week int
}

// Words is how the tables name the slice: "This Week", "This Month",
// "This Quarter", else "This FY".
func (p Period) Words() string {
	switch p.Kind {
	case "week":
		return "This Week"
	case "month":
		return "This Month"
	case "quarter":
		return "This Quarter"
	}
	return "This FY"
}

func unset(value string, present bool) bool {
	return !present || in(rules.UnsetFilterValues, strings.ToLower(closedschools.PyStrip(value)))
}

func widened(query url.Values, previous, current string) bool {
	return query.Has(previous) && query.Has(current) && query.Get(previous) != query.Get(current)
}

// ReadPeriod reads the period filters of query on the day today. ok is false
// for a query the existing view fails on (a year, month or week that is not
// a whole number, or that names no day: the page answers with an error),
// which is left to the existing application.
func ReadPeriod(query url.Values, today time.Time) (p Period, ok bool) {
	today = today.In(kampala)
	p.FY = query.Get("fy")
	if p.FY == "" {
		p.FY = strconv.Itoa(fiscalYear(today))
	}
	rawQuarter, hasQuarter := query.Get("quarter"), query.Has("quarter")
	rawMonth, hasMonth := query.Get("month"), query.Has("month")
	if widened(query, "fy_prev", "fy") {
		hasQuarter, hasMonth = false, false
	} else if widened(query, "quarter_prev", "quarter") {
		hasMonth = false
	}
	if !unset(rawQuarter, hasQuarter) {
		p.Quarter = rawQuarter
	}
	if !unset(rawMonth, hasMonth) {
		month, isInt := closedschools.PyInt(rawMonth)
		if !isInt {
			return p, false
		}
		p.Month, p.HasMonth = month, true
	}
	if first, isQuarter := rules.QuarterFirstMonth[p.Quarter]; !p.HasMonth && isQuarter {
		p.Month, p.HasMonth = first, true
	}
	p.Week = min(5, (today.Day()-1)/7+1)
	if week := query.Get("week"); week != "" {
		n, isInt := closedschools.PyInt(week)
		if !isInt {
			return p, false
		}
		p.Week = n
	}
	fy, isInt := closedschools.PyInt(p.FY)
	if !isInt {
		return p, false
	}
	month := int(today.Month())
	if p.HasMonth {
		month = p.Month
	}
	year := fy
	if month >= 10 {
		year = fy - 1
	}
	// get_week_date_range(year, month, week) is drawn on every request.
	if year < 1 || year > 9999 || month < 1 || month > 12 || p.Week < 1 || p.Week > 5 ||
		(p.Week-1)*7+1 > daysIn(year, month) {
		return p, false
	}
	p.Asked = closedschools.PyStrip(query.Get("period"))
	switch {
	case p.Asked != "":
		p.Kind = p.Asked
	case p.HasMonth:
		p.Kind = "month"
	default:
		p.Kind = "fy"
	}
	return p, true
}

func fiscalYear(day time.Time) int {
	if day.Month() >= time.October {
		return day.Year() + 1
	}
	return day.Year()
}

func daysIn(year, month int) int {
	return time.Date(year, time.Month(month)+1, 0, 0, 0, 0, 0, time.UTC).Day()
}

// Query is the request's query as Django's {% querystring %} edits it: the
// keys in the order the page receives them (the gateway hands its query on
// in key order), a key set in its place or added at the end, a key removed.
type Query struct{ keys, values []string }

// NewQuery is query in the order the existing page receives it.
func NewQuery(query url.Values) Query {
	q := Query{}
	keys := make([]string, 0, len(query))
	for key := range query {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		for _, value := range query[key] {
			q.keys, q.values = append(q.keys, key), append(q.values, value)
		}
	}
	return q
}

// With is the query with key set to value (in its place, or added last).
func (q Query) With(key, value string) Query {
	out := Query{}
	set := false
	for i, k := range q.keys {
		if k == key {
			if set {
				continue
			}
			out.keys, out.values, set = append(out.keys, k), append(out.values, value), true
			continue
		}
		out.keys, out.values = append(out.keys, k), append(out.values, q.values[i])
	}
	if !set {
		out.keys, out.values = append(out.keys, key), append(out.values, value)
	}
	return out
}

// Without is the query without key.
func (q Query) Without(keys ...string) Query {
	out := Query{}
	for i, k := range q.keys {
		if !in(keys, k) {
			out.keys, out.values = append(out.keys, k), append(out.values, q.values[i])
		}
	}
	return out
}

// String is what {% querystring %} writes for the query edited from the
// request: "?" and the query (QueryDict.urlencode), or nothing when both the
// request and the edit are empty.
func (q Query) String(request Query) string {
	if len(q.keys) == 0 && len(request.keys) == 0 {
		return ""
	}
	parts := make([]string, len(q.keys))
	for i, k := range q.keys {
		parts[i] = url.QueryEscape(k) + "=" + url.QueryEscape(q.values[i])
	}
	return "?" + strings.Join(parts, "&")
}

// option is one choice of a select.
type option struct{ value, label string }

// selectFilter is a select as the feed reads it: its value is the first
// option marked selected, else the first option.
func selectFilter(name, label string, options []option, selected func(value string) bool) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: o.label})
		if f.Value == "" && selected(o.value) {
			f.Value = o.value
		}
	}
	if f.Value == "" && len(options) > 0 {
		f.Value = options[0].value
	}
	return f
}

// PeriodFilters are the Fiscal year, Quarter and Month selects
// (partials/my_plan/filters.html) for the period p over the years offered.
func (p Period) PeriodFilters(years []string) []*screensv1.PageFilter {
	fys := []option{}
	for _, y := range years {
		fys = append(fys, option{y, "FY " + y})
	}
	quarters := []option{{"all", "All quarters"}}
	for _, q := range rules.QuarterOptions {
		quarters = append(quarters, option{q, q})
	}
	months := []option{{"all", "All months"}}
	for _, m := range rules.months {
		months = append(months, option{strconv.Itoa(m.value), m.label})
	}
	return []*screensv1.PageFilter{
		selectFilter("fy", "Fiscal year", fys, func(v string) bool { return v == p.FY }),
		selectFilter("quarter", "Quarter", quarters, func(v string) bool {
			if p.Quarter == "" {
				return v == "all"
			}
			return v == p.Quarter
		}),
		selectFilter("month", "Month", months, func(v string) bool {
			if !p.HasMonth {
				return v == "all"
			}
			return v == strconv.Itoa(p.Month)
		}),
	}
}

// Hidden is what the form was drawn with: the ?period= asked for, and the
// year and quarter (fy_prev, quarter_prev).
func (p Period) Hidden() map[string]string {
	hidden := map[string]string{"fy_prev": p.FY, "quarter_prev": "all"}
	if p.Quarter != "" {
		hidden["quarter_prev"] = p.Quarter
	}
	if p.Asked != "" {
		hidden["period"] = p.Asked
	}
	return hidden
}

// Tabs are the horizon rail (This Week, This Month, This Quarter, This FY),
// each a link to the request with its period, and Open Calendar beside it.
func (p Period) Tabs(request Query) *screensv1.PageBlock {
	type tab struct {
		label, kind string
		drop        []string
		active      bool
	}
	tabs := []tab{
		{"This Week", "week", []string{"month", "quarter"}, p.Kind == "week"},
		{"This Month", "month", nil, p.Kind == "month"},
		{"This Quarter", "quarter", []string{"month"}, p.Kind == "quarter"},
		{"This FY", "fy", []string{"month", "quarter"}, p.Kind == "fy" || p.Kind == ""},
	}
	out := &screensv1.PageLinkTabs{Beside: &screensv1.PageAction{
		Key: "beside", Label: "Open Calendar", Primary: true, Enabled: true, Href: "/calendar",
	}}
	for _, t := range tabs {
		out.Tabs = append(out.Tabs, &screensv1.PageLinkTab{
			Label: t.label, Href: request.With("period", t.kind).Without(t.drop...).String(request), Active: t.active,
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: out}}
}
