package main

import "context"

func init() { pageQuestions["/leave/policies"] = leavePoliciesQuestions }

// leavePoliciesQuestions are Leave Policies': the page as it opens and with
// keys it does not read (it has no filters of its own).
func leavePoliciesQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"q": "sick"}, {"fy": "2026"}}
}
