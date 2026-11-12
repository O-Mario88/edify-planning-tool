package main

import "context"

func init() { pageQuestions["/planning"] = planningQuestions }

// planningQuestions are the Planning page's Client and Core tabs: as it
// opens, each grouping, years and quarters, every readiness, support and SSA
// filter value, searches, later pages and page sizes, and every district and
// the first people the page offers.
func planningQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}, {"tab": "core"}, {"group": "owner"}, {"group": "name"}, {"tab": "core", "group": "owner"},
		{"fy": "2026"}, {"fy": "2028"}, {"fy": "2025", "tab": "core"}, {"quarter": "Q3"},
		{"page": "2"}, {"page": "5"}, {"page": "99"}, {"per_page": "50"}, {"per_page": "20", "page": "2"},
		{"q": "central"}, {"q": "1650"}, {"q": "zzz"}, {"q": "Paul"},
		{"school_type": "core"}, {"cluster_status": "unclustered"}, {"planning_readiness": "data_cleanup_required"},
		{"ssa_status": "done"}, {"ssa_status": "not_done"}, {"ssa_status": "scheduled"}, {"district": "nonsense"},
		{"tab": "partner"}, {"tab": "partner", "group": "owner"}, {"tab": "scheduled"}, {"tab": "scheduled", "fy": "2026"},
		{"tab": "clusters"}, {"tab": "clusters", "page": "2"}, {"tab": "clusters", "q": "cluster b"},
		{"tab": "clusters", "planning_readiness": "not_scheduled"}, {"tab": "clusters", "fy": "2026"}}
	for _, v := range []string{"requires_cluster", "ready_for_baseline_ssa", "ready_for_support_planning", "scheduled", "in_my_plan"} {
		out = append(out, map[string]string{"planning_readiness": v})
	}
	for _, v := range []string{"staff_managed", "partner_support", "my_scheduled_visits", "visit_not_planned",
		"training_not_planned", "both_planned", "awaiting_verification", "completed", "needs_replanning", "bogus"} {
		out = append(out, map[string]string{"support": v})
	}
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			if f.GetName() != "district" && f.GetName() != "staff" {
				continue
			}
			for i, o := range f.GetOptions() {
				if o.GetValue() != "All" && i <= 3 {
					out = append(out, map[string]string{f.GetName(): o.GetValue()})
				}
			}
		}
	}
	return out
}
