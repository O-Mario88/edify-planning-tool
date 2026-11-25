package main

import "context"

// The Schools & Coverage lens (Team Oversight's ?view=coverage) adds its
// questions to the page's.
func init() {
	before := pageQuestions["/team-planning-oversight/"]
	pageQuestions["/team-planning-oversight/"] = func(ctx context.Context, r *pageRun, token string) []map[string]string {
		out := coverageLensQuestions()
		if before != nil {
			out = append(before(ctx, r, token), out...)
		}
		return out
	}
}

// coverageLensQuestions are the coverage lens's: every period in each year
// the selector offers, months and quarters either side of the year's turn,
// weeks, the pages of its three tables (a page past the end and one that is
// not a number), an owner and family filter, and the country lens's Lead.
func coverageLensQuestions() []map[string]string {
	out := []map[string]string{
		{"view": "coverage", "period": "month", "month": "10"}, {"view": "coverage", "period": "month", "month": "3"},
		{"view": "coverage", "period": "quarter", "quarter": "Q1"}, {"view": "coverage", "period": "quarter", "quarter": "Q4"},
		{"view": "coverage", "period": "week", "week": "2026-W45"}, {"view": "coverage", "period": "week", "week": "2026-W40"},
		{"view": "coverage", "fy": "2026", "period": "month", "month": "11"},
		{"view": "coverage", "trained_page": "2"}, {"view": "coverage", "untrained_page": "2"},
		{"view": "coverage", "untrained_page": "99"}, {"view": "coverage", "untrained_page": "abc"},
		{"view": "coverage", "g1_page": "2"}, {"view": "coverage", "fy": "2026", "g1_page": "2"},
		{"view": "coverage", "owner": "mine"}, {"view": "coverage", "activity": "trainings"},
		{"view": "coverage", "program_lead": "cmw9p7axf00zhz7ekherr"}, {"view": "coverage", "officer": "cmw9p7bwp00t19mekheun"},
	}
	for _, fy := range []string{"2025", "2026", "2027", "2028"} {
		for _, period := range []string{"week", "month", "quarter", "fy"} {
			out = append(out, map[string]string{"view": "coverage", "fy": fy, "period": period})
		}
	}
	return out
}
