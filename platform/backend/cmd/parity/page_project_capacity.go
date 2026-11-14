package main

import "context"

func init() { pageQuestions["/projects/capacity"] = projectCapacityQuestions }

// projectCapacityQuestions are Project Capacity's: the page as it opens (the
// first project's tab); a project the reader does not direct, an empty and
// a padded one; and a key the page does not read. The golden asks each
// project's tab by its id. The staff pager's key (staff_page-<id>) is not
// asked: it holds a hyphen, which the feed drops and the screens service
// refuses (BACKLOG screens-query-key-digits, go-fix-capacity-pager).
func projectCapacityQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"project", "nothing"}, {"project", ""}, {"project", "  "}, {"fy", "2025"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return out
}
