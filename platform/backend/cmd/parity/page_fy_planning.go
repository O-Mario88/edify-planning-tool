package main

import "context"

func init() { pageQuestions["/planning/fiscal-years"] = fyPlanningQuestions }

// fyPlanningQuestions are Fiscal Year Planning's: the page as it opens, and
// keys it does not read.
func fyPlanningQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"fy": "2028"}, {"q": "2027"}}
}
