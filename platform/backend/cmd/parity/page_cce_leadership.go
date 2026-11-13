package main

import "context"

func init() {
	pageQuestions["/cce-leadership/reports"] = cceReportsQuestions
	pageQuestions["/cce-leadership/feedback"] = cceReportsQuestions
	pageQuestions["/cce-leadership/engagements"] = cceEngagementQuestions
	pageQuestions["/my-coaching"] = myCoachingQuestions
}

// cceReportsQuestions are the monthly CCE reports': the page as it opens,
// the register's page in and out of range and not a number, and a key it
// does not read.
func cceReportsQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"register_page": "2"}, {"register_page": "x"}, {"open": "nothing"}}
}

// cceEngagementQuestions are the CCE Engagement Log's: the page as it opens,
// each filter with a value it offers and one it does not, and a page.
func cceEngagementQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"kind": "pl_coaching"}, {"kind": "bogus"}, {"country": "Uganda"}, {"country": "Atlantis"},
		{"kind": "site_visit", "country": "Uganda"}, {"register_page": "2"}}
}

// myCoachingQuestions are My Coaching's: the page as it opens, each filter
// with a value it offers and one it does not.
func myCoachingQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"kind": "recognition"}, {"kind": "nope"}, {"state": "awaiting"}, {"state": "acknowledged"},
		{"state": "draft"}, {"kind": "one_to_one", "state": "awaiting"}}
}
