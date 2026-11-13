package main

import "context"

// The page's other lenses register their questions too (init order is the
// file names'), so the Training Summary's are added to theirs.
func init() {
	before := pageQuestions["/team-planning-oversight/"]
	pageQuestions["/team-planning-oversight/"] = func(ctx context.Context, r *pageRun, token string) []map[string]string {
		out := trainingSummaryQuestions(ctx, r, token)
		if before != nil {
			out = append(before(ctx, r, token), out...)
		}
		return out
	}
}

// trainingSummaryQuestions are the Training Summary's (Team Oversight's
// ?view=trainings, the lens Go draws): the lens as it opens, spelt with
// stray spaces and capitals; every year it offers, one it does not, one with
// stray spaces and one that is not a year; the Summary tab named and a tab
// that is not one; each Programme Lead's team, one with stray spaces and one
// that is no Lead; keys the feed does not pass and the API format; and the filters together.
func trainingSummaryQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	leads := []string{"cmw9p7axf00zhz7ekherr", "cmw9p7b6a00e4s8ekhefr", "cmw9p7bf200eymgekhexn", "cmw9p7bnw00bt5kekhesg"}
	out := []map[string]string{
		{"view": "trainings"}, {"view": " Trainings "}, {"view": "TRAININGS"},
		{"view": "trainings", "tab": "summary"}, {"view": "trainings", "tab": " SUMMARY "}, {"view": "trainings", "tab": "nonsense"},
		{"view": "trainings", "program_lead": "nobody"}, {"view": "trainings", "program_lead": " " + leads[0] + " "},
		{"view": "trainings", "export": "csv"}, {"view": "trainings", "format": "json"},
		{"view": "trainings", "fy": "2026", "program_lead": leads[1]},
	}
	for _, fy := range []string{"2025", "2026", "2027", "2028", "1999", " 2026 ", "abc"} {
		out = append(out, map[string]string{"view": "trainings", "fy": fy})
	}
	for _, lead := range leads {
		out = append(out, map[string]string{"view": "trainings", "program_lead": lead})
	}
	return out
}
