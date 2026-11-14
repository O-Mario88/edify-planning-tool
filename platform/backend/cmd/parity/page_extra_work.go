package main

import "context"

func init() { pageQuestions["/extra-work"] = extraWorkQuestions }

// extraWorkQuestions are Extra Assigned Work's: the page as it opens; this
// year, the last, a year with nothing, one with spaces around it and one that
// is not a year; the table's page in and out of range and not a number; and
// a key the page does not read.
func extraWorkQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"fy", "2027"}, {"fy", "2026"}, {"fy", "1999"}, {"fy", " 2026 "}, {"fy", "FY2027"}, {"fy", "a&b"},
		{"extra_work_mine_page", "2"}, {"extra_work_mine_page", "abc"}, {"view", "all"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return out
}
