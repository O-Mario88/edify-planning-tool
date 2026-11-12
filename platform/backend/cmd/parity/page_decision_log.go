package main

import "context"

func init() { pageQuestions["/decision-log"] = decisionLogQuestions }

// decisionLogQuestions are the Decision Log's: the page as it opens; every
// lookback window it offers, one it does not, and windows out of range or
// not a number; every group, an unknown one and one with a window; an actor
// (the seeded one, and one who decided nothing); the table's page in and
// out of range; and a key the page does not read.
func decisionLogQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"days", "7"}, {"days", "30"}, {"days", "90"}, {"days", "45"}, {"days", "1"}, {"days", "0"},
		{"days", "-3"}, {"days", "400"}, {"days", "abc"}, {"days", " 90 "}, {"days", "9_0"},
		{"group", "Money"}, {"group", "People"}, {"group", "Programme"}, {"group", "Quality"},
		{"group", "Escalation"}, {"group", "Impact"}, {"group", "Other"}, {"group", "money"},
		{"actor", "cmw9p7bny006entekhee1"}, {"actor", "nobody"},
		{"decision_log_log_rows_page", "2"}, {"decision_log_log_rows_page", "abc"}, {"fy", "2025"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out,
		map[string]string{"group": "Programme", "days": "7"},
		map[string]string{"group": "Programme", "days": "365", "decision_log_log_rows_page": "1"})
	return out
}
