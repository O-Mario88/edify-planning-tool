package main

import "context"

func init() { pageQuestions["/ia/duplicates/"] = iaDuplicatesQuestions }

// iaDuplicatesQuestions are Duplicate Review's: the page as it opens and with
// keys it does not read (it has no filters).
func iaDuplicatesQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"q": "visit"}, {"status": "ignored"}}
}
