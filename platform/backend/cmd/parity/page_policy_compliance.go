package main

import "context"

func init() { pageQuestions["/policy-compliance"] = policyComplianceQuestions }

// policyComplianceQuestions are Policy Compliance's: the page as it opens;
// each status filter and one it does not know; a policy that does not exist;
// a role; the table's second page and one out of range; and a key it does
// not read.
func policyComplianceQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"state", "pending"}, {"state", "agreed"}, {"state", "disagreed"}, {"state", "bogus"}, {"document", "nothing"},
		{"role", "CCEO"}, {"rows_page", "2"}, {"rows_page", "99"}, {"fy", "2025"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return out
}
