package main

import "context"

func init() { pageQuestions["/escalations"] = escalationsQuestions }

// escalationsQuestions are Escalations': the page as it opens; the shared
// page of every list in and out of range and not a number; and what an
// analytics drill-down hands the raise form (a subject and detail padded,
// with markup and on several lines, every category, an unknown one, and the
// scope it carries hidden); and a key the page does not read.
func escalationsQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"escalation_rows_page", "2"}, {"escalation_rows_page", "abc"}, {"escalation_rows_page", "-1"},
		{"subject", "  A cluster <b>cannot</b> be covered & more  "}, {"detail", "Line one\n  line two  "},
		{"category", "funding_gap"}, {"category", "partner_performance"}, {"category", "staffing"},
		{"category", "project_direction"}, {"category", "policy_exception"}, {"category", "regional_tradeoff"},
		{"category", "school_blocker"}, {"category", "other"}, {"category", "Staffing"}, {"category", " staffing "},
		{"scope_name", "St. Mary's"}, {"fy", "2025"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return append(out, map[string]string{
		"subject": "Funding gap", "detail": "Two districts", "category": "funding_gap",
		"scope_type": "district", "scope_id": "d1", "scope_name": "Gulu",
	})
}
