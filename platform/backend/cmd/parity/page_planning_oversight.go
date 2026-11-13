package main

import "context"

func init() {
	pageQuestions["/team-planning-oversight/"] = planningOversightQuestions
	pageQuestions["/country-planning-oversight/"] = planningOversightQuestions
}

// planningOversightQuestions are Planning Oversight's and Country
// Oversight's doors (piece 1): the page as it opens; every lens either page
// names, one it does not and one with stray spaces; the periods; a Lead tab,
// an owner tab and an activity strip; the formats the feed renders and one
// it does not. A reader either page refuses is refused all of them; a reader
// it opens for is the existing application's.
func planningOversightQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, view := range []string{
		"planning", "plan", "trainings", "portfolio", "coverage", "targets", "monitor",
		"execution", "clusters", "projects", "nonsense", " trainings ",
	} {
		out = append(out, map[string]string{"view": view})
	}
	for _, kv := range [][2]string{
		{"period", "week"}, {"period", "month"}, {"period", "quarter"}, {"period", "fy"},
		{"fy", "2026"}, {"fy", "abc"}, {"owner", "mine"}, {"activity", "visits"},
		{"program_lead", "nobody"}, {"format", "json"}, {"format", "xml"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return out
}
