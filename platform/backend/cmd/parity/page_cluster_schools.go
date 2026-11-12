package main

import "context"

func init() { pageQuestions["/partials/clusters/{id}/schools"] = clusterSchoolQuestions }

// clusterSchoolQuestions are a cluster card's schools list's: as the card
// opens it, and for another year, a year with no plans and a year that is
// not one.
func clusterSchoolQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"fy": "2026"}, {"fy": "2025"}, {"fy": "1999"}}
}
