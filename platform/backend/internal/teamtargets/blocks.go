package teamtargets

import (
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

type option struct{ value, label string }

func filterOf(name, label, value string, options []option) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label, Value: value}
	found := false
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: o.label})
		found = found || o.value == value
	}
	if !found && len(options) > 0 {
		// A select names its chosen option, else (the browser) its first.
		f.Value = options[0].value
	}
	return f
}

// fyOptions is fy_options: FY 2025 up to the year after the operational
// one, at least through 2027.
func fyOptions(operationalFY string) []option {
	current, _ := strconv.Atoi(operationalFY)
	out := []option{}
	for y := 2025; y <= max(current+1, 2027); y++ {
		fy := strconv.Itoa(y)
		out = append(out, option{fy, targetsFYLabel(fy)})
	}
	return out
}

func targetsFYLabel(fy string) string {
	n, err := strconv.Atoi(fy)
	if err != nil || len(fy) != 4 {
		return "FY " + fy
	}
	return "FY " + strconv.Itoa(n-1) + "/" + fy[2:]
}

// filtersBlock is the workspace's filter form as the feed reads it.
func (d *data) filtersBlock() *screensv1.PageBlock {
	months := []option{}
	for m := 1; m <= 12; m++ {
		months = append(months, option{strconv.Itoa(m), targets.MonthLabel(d.fy, m)})
	}
	categories := []option{{"overall", "Overall weighted performance"}}
	for _, a := range d.t.areas {
		categories = append(categories, option{a.Key, a.Label})
	}
	districts := []option{{"", "All districts"}}
	for _, name := range d.port.districts {
		districts = append(districts, option{name, name})
	}
	members := []option{{"", "All team members"}}
	for _, m := range d.all {
		members = append(members, option{m.UserID, m.Name})
	}
	order := ""
	if d.ranked {
		order = rules.OrderRanked
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Hidden: map[string]string{"view": "targets"},
		Filters: []*screensv1.PageFilter{
			filterOf("fy", "Fiscal year", d.fy, fyOptions(d.operationalFY)),
			filterOf("month", "Month", strconv.Itoa(d.month), months),
			filterOf("category", "Performance priority", d.category, categories),
			filterOf("district", "District", d.district, districts),
			filterOf("team_member", "Team member", d.member, members),
			filterOf("order", "Order", order, []option{{"", "By team"}, {rules.OrderRanked, "Ranked by full-year achievement"}}),
		},
	}}}
}

// stripBlock is the "Team target progress" figures (summary_kpis through
// components/context_metrics.html) as the feed reads them: label and value.
func stripBlock(teamPct, onTrackRate, atRisk, quarterPct, fyPct, plans int) *screensv1.PageBlock {
	label := func(key string) string { return rules.MetricLabels["targets_team_targets_"+key] }
	pct := func(v int) string { return strconv.Itoa(v) + "%" }
	metric := func(key, value string) *screensv1.PageMetric {
		return &screensv1.PageMetric{Label: label(key), Value: value}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Team target progress",
		Metrics: []*screensv1.PageMetric{metric("team_achievement", pct(teamPct)), metric("monthly_on_track", pct(onTrackRate)),
			metric("at_risk_staff", strconv.Itoa(atRisk)), metric("current_quarter", pct(quarterPct)),
			metric("fy_achievement", pct(fyPct)), metric("recovery_plans", strconv.Itoa(plans))}}}}
}
