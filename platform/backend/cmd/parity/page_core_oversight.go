package main

import "context"

func init() { pageQuestions["/core-schools-oversight/"] = coreOversightQuestions }

// coreOversightQuestions are Core School Oversight's: the page as it opens;
// every year it offers, one it does not, one with stray spaces; each tab Go
// draws (the two tabs of planned work are My Plan's and stay the existing
// application's) and one that is not a tab; every grouping; every filter
// value, values with stray spaces and values that are not values; every
// sort; searches by name, by School ID and for nothing; pages in and out of
// range and pages that are not pages; and filters, tabs and pages together.
func coreOversightQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"fy", "2028"}, {"fy", "2027"}, {"fy", "2026"}, {"fy", "2025"}, {"fy", "1999"}, {"fy", " 2026 "}, {"fy", "abc"},
		{"tab", "schools"}, {"tab", "groups"}, {"tab", "attention"}, {"tab", "recommendations"}, {"tab", "champion"},
		{"tab", "nonsense"}, {"tab", " attention "},
		{"trajectory", "improved"}, {"trajectory", "declined"}, {"trajectory", "not_comparable"}, {"trajectory", " declined "}, {"trajectory", "nonsense"},
		{"attention", "Critical SSA area"}, {"attention", "Package incomplete"}, {"attention", "No current-year SSA"},
		{"attention", "Partner hand-over not scheduled"}, {"attention", "nonsense"},
		{"readiness", "Not Yet Ready"}, {"readiness", "Progressing"}, {"readiness", "Champion"}, {"readiness", "Insufficient Evidence"},
		{"district", "Mukono"}, {"district", " Mukono "}, {"district", "Nowhere"},
		{"type", "core"}, {"type", "champion"}, {"type", " core "}, {"type", "client"},
		{"sort", "latest"}, {"sort", "change"}, {"sort", "package"}, {"sort", "attendance"}, {"sort", "nonsense"},
		{"q", "kimenyedde"}, {"q", "1006"}, {"q", "  CENTRAL  "}, {"q", "no such school"},
		{"page", "1"}, {"page", "2"}, {"page", "3"}, {"page", "999"}, {"page", "0"}, {"page", "-1"}, {"page", "abc"}, {"page", " 2 "},
		{"group", "district"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	for _, group := range []string{"cceo", "district", "sub_region", "cluster", "nonsense"} {
		out = append(out, map[string]string{"tab": "groups", "group": group})
	}
	for _, sort := range []string{"latest", "package"} {
		for _, tab := range []string{"attention", "champion", "recommendations"} {
			out = append(out, map[string]string{"tab": tab, "sort": sort})
		}
	}
	return append(out,
		map[string]string{"fy": "2026", "page": "2"},
		map[string]string{"sort": "latest", "page": "3", "district": "Mukono"},
		map[string]string{"tab": "attention", "attention": "Critical SSA area", "q": "primary"},
		map[string]string{"tab": "champion", "readiness": "Progressing", "fy": "2027"},
		map[string]string{"tab": "groups", "group": "cluster", "type": "core", "trajectory": "not_comparable"},
		map[string]string{"tab": "recommendations", "q": "kimenyedde"},
		map[string]string{"fy": "2026", "tab": "recommendations"},
		map[string]string{"fy": "2026", "download": "1", "export": "csv"},
	)
}
