package main

import "context"

func init() {
	pageQuestions["/admin-ops/support"] = adminOpsStatusQuestions
	pageQuestions["/admin-ops/incidents"] = adminOpsStatusQuestions
}

// adminOpsStatusQuestions are Support Tickets' and System Incidents': the
// register as it opens, filtered by each kind of status (one it holds, one
// it does not know, an empty and a padded one), and a key it does not read.
// The Maintenance Calendar reads no key and is asked only as it opens.
func adminOpsStatusQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"status", "open"}, {"status", "resolved"}, {"status", "submitted"}, {"status", "verification"},
		{"status", "bogus"}, {"status", ""}, {"status", " open "}, {"fy", "2025"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return out
}
