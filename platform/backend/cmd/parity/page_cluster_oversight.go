package main

import "context"

func init() { pageQuestions["/cluster-oversight/"] = clusterOversightQuestions }

// clusterOversightQuestions are Cluster Oversight's, as the app opens it
// (the Command Center): the page as it opens; every year it offers, one it
// does not, and one with stray spaces; pages of its table in and out of
// range and pages that are not pages; the SSA area and Impact view its
// other sections read, which this one ignores; a download's keys the feed does not
// pass on; and a year and a page together.
func clusterOversightQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"fy", "2028"}, {"fy", "2027"}, {"fy", "2026"}, {"fy", "2025"}, {"fy", "1999"}, {"fy", " 2026 "}, {"fy", "abc"},
		{"rows_page", "1"}, {"rows_page", "2"}, {"rows_page", "999"}, {"rows_page", "0"}, {"rows_page", "-1"},
		{"rows_page", "abc"}, {"rows_page", " 2 "},
		{"area", "leadership"}, {"area", "nonsense"}, {"view", "courses"}, {"view", "clusters"}, {"view", "nonsense"},
		{"page", "2"}, {"q", "cluster b"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return append(out,
		map[string]string{"fy": "2026", "rows_page": "2"},
		map[string]string{"fy": "2025", "area": "leadership", "view": "courses"},
		map[string]string{"fy": "2026", "download": "1", "export": "csv"},
	)
}
