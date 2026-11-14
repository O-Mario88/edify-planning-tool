package main

import "context"

func init() { pageQuestions["/quality-checks"] = qualityFlagsQuestions }

// qualityFlagsQuestions are Quality Flags': the page as it opens; what an
// analytics drill-down hands the raise form (a scope padded and with markup,
// a Programme Lead in and out of reach, a note on several lines, a
// category); a To-Do's ?resolve= link; and a key the page does not read.
func qualityFlagsQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"scope_name", "  St. Mary's <b>PS</b> & more  "}, {"assign_to", "nobody"}, {"note", "Line one\n  line two  "},
		{"category", "data-quality"}, {"resolve", "nothing"}, {"fy", "2025"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return append(out, map[string]string{"scope_type": "school", "scope_id": "s1", "scope_name": "Gulu PS", "note": "Look", "category": "ssa"})
}
