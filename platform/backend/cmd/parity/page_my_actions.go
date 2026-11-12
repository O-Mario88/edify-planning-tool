package main

import "context"

func init() {
	pageQuestions["/actions/mine"] = myActionsQuestions
	// Actions Sent reads the same rows from the sender's end, so it is asked
	// the same questions.
	pageQuestions["/actions/sent"] = myActionsQuestions
}

// myActionsQuestions are My Actions': the page as it opens; every tab, one
// padded, one in capitals and one that is not a tab; the queue's page in
// and out of range and not a number, alone and with a tab; and a key the
// page does not read.
func myActionsQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"tab", "open"}, {"tab", "overdue"}, {"tab", "resolved"}, {"tab", "all"}, {"tab", " all "},
		{"tab", "Open"}, {"tab", "bogus"}, {"table_rows_page", "2"}, {"table_rows_page", "999"},
		{"table_rows_page", "abc"}, {"table_rows_page", "0"}, {"fy", "2025"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return append(out, map[string]string{"tab": "all", "table_rows_page": "2"})
}
