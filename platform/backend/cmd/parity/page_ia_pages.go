package main

import "context"

func init() {
	pageQuestions["/ia/duplicates/"] = iaDuplicatesQuestions
	pageQuestions["/ia/returned/"] = iaReturnedQuestions
	pageQuestions["/ia/history/"] = iaReturnedQuestions
}

// iaDuplicatesQuestions are Duplicate Review's: the page as it opens and with
// keys it does not read (it has no filters).
func iaDuplicatesQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"q": "visit"}, {"status": "ignored"}}
}

// iaReturnedQuestions are Returned Activities': the page as it opens, its
// pages in and out of range and not a number, and a key it does not read.
func iaReturnedQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"page": "2"}, {"page": "abc"}, {"q": "visit"}}
}
