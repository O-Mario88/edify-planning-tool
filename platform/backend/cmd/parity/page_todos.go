package main

import "context"

func init() { pageQuestions["/todos"] = todoQuestions }

// todoQuestions are the To-Do page's: the page as it opens, and keys it does
// not read (its chips filter on the device; nothing it draws is a query).
func todoQuestions(context.Context, *pageRun, string) []map[string]string {
	return []map[string]string{{}, {"cat": "Finance"}, {"prio": "high"}, {"page": "2"}, {"q": "school"}}
}
