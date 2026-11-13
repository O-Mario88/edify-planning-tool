package main

import "context"

func init() {
	for _, path := range []string{"/org-structure", "/recognition", "/health-safety", "/onboarding", "/offboarding", "/candidate-pipeline", "/compliance-register", "/hr-audit-log", "/workforce-planning", "/policies", "/recovery-plans", "/performance-reviews", "/compensation-benefits", "/pulse-surveys", "/hr-analytics"} {
		pageQuestions[path] = hrRegisterQuestions
	}
}

// hrRegisterQuestions are an HR register's: the page as it opens; a search
// that finds people, one by country, one by role, one that finds nobody, one
// with spaces around it and ones holding LIKE's own wildcards; the register's
// page in and out of range and not a number; and a key the page does not
// read.
func hrRegisterQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"q", "program"}, {"q", "uganda"}, {"q", "CCEO"}, {"q", "zzz-nobody"}, {"q", "  lead  "}, {"q", "%"}, {"q", "_"},
		{"q", "a"}, {"page", "2"}, {"page", "abc"}, {"view", "all"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out, map[string]string{"q": "a", "page": "2"})
	return out
}
