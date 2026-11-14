package main

import "context"

func init() { pageQuestions["/partner/users"] = partnerUsersQuestions }

// partnerUsersQuestions are the Users page's: the page as it opens, the
// roster's second page and one out of range, and a key it does not read.
// Its readers are partner logins, which the default parity accounts do not
// hold: run it with EW_USERS naming them.
func partnerUsersQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	return []map[string]string{{}, {"roster_page": "2"}, {"roster_page": "x"}, {"fy": "2025"}}
}
