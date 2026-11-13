package main

import "context"

// The portfolio lens shares its path with the other Planning Oversight
// lenses, whose question sets register under the path itself, so its own set
// registers under the path with an {id}: run it with
// -path '/team-planning-oversight/{id}' -ids ” (the id is empty, so the page
// asked is /team-planning-oversight/ and these are its questions).
func init() { pageQuestions["/team-planning-oversight/{id}"] = oversightPortfolioQuestions }

// oversightPortfolioQuestions are the portfolio lens's (Planning Oversight's
// ?view=portfolio): the lens as it opens, spelt with stray spaces and
// capitals; every year it offers, one it does not, one with stray spaces and
// one that is not a year; each planning state, one with stray spaces and one
// that is not a state; the seed's Programme Lead, one with stray spaces, "all"
// and one that is no Lead; the seed's district, "all" and one that is none;
// the officer's pages in and out of range and not a number, alone and under
// a filter; a planning follow-up; keys the feed does not pass, a list of ids
// and the API format; and the filters together.
func oversightPortfolioQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	const (
		lead     = "cmw9p7axf00zhz7ekherr"
		district = "cmw9p546g00kclteihg5e"
		pager    = "portfolio_cmw9p7bwp00t19mekheun_page"
	)
	out := []map[string]string{
		{"view": "portfolio"}, {"view": " Portfolio "}, {"view": "PORTFOLIO"},
		{"view": "portfolio", "planned": "planned"}, {"view": "portfolio", "planned": "unplanned"},
		{"view": "portfolio", "planned": " planned "}, {"view": "portfolio", "planned": "nonsense"},
		{"view": "portfolio", "program_lead": lead}, {"view": "portfolio", "program_lead": " " + lead + " "},
		{"view": "portfolio", "program_lead": "all"}, {"view": "portfolio", "program_lead": "nobody"},
		{"view": "portfolio", "district": district}, {"view": "portfolio", "district": "All"},
		{"view": "portfolio", "district": "nowhere"},
		{"view": "portfolio", pager: "2"}, {"view": "portfolio", pager: "14"}, {"view": "portfolio", pager: "99"},
		{"view": "portfolio", pager: "0"}, {"view": "portfolio", pager: "abc"},
		{"view": "portfolio", "planned": "unplanned", pager: "14"},
		{"view": "portfolio", "followup": "abc"}, {"view": "portfolio", "export": "csv"},
		{"view": "portfolio", "format": "json"}, {"view": "portfolio", "ids": "a,b"},
		{"view": "portfolio", "fy": "2026", "planned": "planned", "district": district, "program_lead": lead},
	}
	for _, fy := range []string{"2025", "2026", "2027", "2028", "2030", "1999", " 2026 ", "abc"} {
		out = append(out, map[string]string{"view": "portfolio", "fy": fy})
	}
	return out
}
