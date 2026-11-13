package main

import "context"

func init() {
	pageQuestions["/work-plan"] = workPlanQuestions
	// The Work Plan orders every row itself (planned date, made, id), so
	// its rows are compared exactly as each side gives them: no run of
	// rows sharing a name is re-sorted (sortTies).
	exactOrder["/work-plan"] = true
}

// exactOrder are the pages whose table rows are compared in the order each
// side gives them.
var exactOrder = map[string]bool{}

// workPlanQuestions are the Work Plan's: the page as it opens; each view and
// one that is not; months and quarters in and out of range, padded and in
// lower case; years in and out of the menu, padded, and a year changed with
// the form (which resets the period); every status the select offers and
// one it does not; every activity type and executor, and one of each that is
// not; each person and project the page offers and ones it does not; each
// drill-down flag and one that is not; a Program Lead's two audiences; pages
// of the detail table in and out of range; a download's key, which the feed
// never passes; and filters together.
func workPlanQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"view", "month"}, {"view", "quarter"}, {"view", "fy"}, {"view", "week"}, {"view", " fy "},
		{"period", "10"}, {"period", "12"}, {"period", "1"}, {"period", "3"}, {"period", "9"},
		{"period", "0"}, {"period", "13"}, {"period", "abc"}, {"period", " 3 "}, {"period", "1_1"}, {"period", "Q2"},
		{"fy", "2025"}, {"fy", "2026"}, {"fy", "2027"}, {"fy", "2028"}, {"fy", "1999"}, {"fy", " 2027 "},
		{"fy_prev", "2026"},
		{"status", "bogus"}, {"status", " scheduled "},
		{"activity_type", "bogus"}, {"executor", "staff"}, {"executor", "partner"}, {"executor", "bogus"},
		{"responsible", "nobody"}, {"project", "nothing"},
		{"flag", "pending_approval"}, {"flag", "cost_missing"}, {"flag", "at_risk"}, {"flag", "bogus"},
		{"scope", "own"}, {"scope", "team"}, {"scope", "bogus"},
		{"wp_page", "2"}, {"wp_page", "0"}, {"wp_page", "abc"}, {"wp_page", "999"},
		{"export", "xlsx"}, {"x", "1"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out,
		map[string]string{"view": "quarter", "period": "Q1"},
		map[string]string{"view": "quarter", "period": "Q2"},
		map[string]string{"view": "quarter", "period": "Q3"},
		map[string]string{"view": "quarter", "period": "Q4"},
		map[string]string{"view": "quarter", "period": "q2"},
		map[string]string{"view": "quarter", "period": "Q9"},
		map[string]string{"view": "quarter", "period": "11"},
		map[string]string{"fy": "2026", "view": "fy"},
		map[string]string{"fy": "2026", "view": "quarter"},
		map[string]string{"fy": "2026", "period": "3"},
		map[string]string{"fy": "2026", "fy_prev": "2027", "period": "3"},
		map[string]string{"fy": "2026", "fy_prev": "2026", "period": "3"},
		map[string]string{"fy": "2028", "fy_prev": "2027", "view": "quarter", "period": "Q3"},
		map[string]string{"view": "fy", "flag": "cost_missing"},
		map[string]string{"view": "fy", "flag": "at_risk", "scope": "own"},
		map[string]string{"view": "fy", "status": "scheduled", "executor": "staff"},
		map[string]string{"view": "fy", "wp_page": "2"},
		map[string]string{"view": "quarter", "period": "Q1", "flag": "pending_approval", "activity_type": "school_visit"},
	)
	statuses, types := []string{}, []string{}
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			for _, o := range f.GetOptions() {
				if o.GetValue() == "" {
					continue
				}
				switch f.GetName() {
				case "status":
					statuses = append(statuses, o.GetValue())
				case "activity_type":
					types = append(types, o.GetValue())
				case "responsible", "project":
					out = append(out, map[string]string{f.GetName(): o.GetValue()})
				}
			}
		}
	}
	for _, s := range statuses {
		out = append(out, map[string]string{"status": s}, map[string]string{"status": s, "view": "fy"})
	}
	for _, t := range types {
		out = append(out, map[string]string{"activity_type": t, "view": "fy"})
	}
	return out
}
