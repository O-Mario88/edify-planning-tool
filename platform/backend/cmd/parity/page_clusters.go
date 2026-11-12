package main

import "context"

func init() { pageQuestions["/clusters"] = clusterQuestions }

// clusterQuestions are the Clusters page's: the page as it opens, every
// filter value the page offers, a search, later pages and pages that are not
// pages, and two filters together.
func clusterQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"page", "2"}, {"page", "3"}, {"page", "999"}, {"page", "0"}, {"page", "abc"}, {"page", " 2 "},
		{"fy", "2026"}, {"fy", "2025"}, {"fy", "1999"}, {"quarter", "Q2"}, {"quarter", "Q9"},
		{"q", "cluster b"}, {"q", "MUKONO"}, {"q", "%"}, {"q", "zzz"},
		{"ssa_status", "done"}, {"ssa_status", "not_done"},
		{"cluster_risk", "critical"}, {"cluster_risk", "needs_attention"}, {"cluster_risk", "healthy"},
		{"activity_status", "pending"}, {"activity_status", "completed"},
		{"district", "nonsense"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out, map[string]string{"cluster_risk": "critical", "page": "2"})
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			switch f.GetName() {
			case "district", "sub_county", "staff":
				for i, o := range f.GetOptions() {
					if o.GetValue() != "" && (f.GetName() != "staff" || i <= 3) {
						out = append(out, map[string]string{f.GetName(): o.GetValue()})
					}
				}
			}
		}
	}
	return out
}
