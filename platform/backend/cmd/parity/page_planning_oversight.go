package main

import "context"

func init() {
	pageQuestions["/team-planning-oversight/"] = func(ctx context.Context, run *pageRun, who string) []map[string]string {
		return append(planningOversightQuestions(ctx, run, who), teamPlanQuestions()...)
	}
	pageQuestions["/country-planning-oversight/"] = planningOversightQuestions
}

// planningOversightQuestions are Planning Oversight's and Country
// Oversight's doors (piece 1): the page as it opens; every lens either page
// names, one it does not and one with stray spaces; the periods; a Lead tab,
// an owner tab and an activity strip; the formats the feed renders and one
// it does not. A reader either page refuses is refused all of them; a reader
// it opens for is the existing application's.
func planningOversightQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, view := range []string{
		"planning", "plan", "trainings", "portfolio", "coverage", "targets", "monitor",
		"execution", "clusters", "projects", "nonsense", " trainings ",
	} {
		out = append(out, map[string]string{"view": view})
	}
	for _, kv := range [][2]string{
		{"period", "week"}, {"period", "month"}, {"period", "quarter"}, {"period", "fy"},
		{"fy", "2026"}, {"fy", "abc"}, {"owner", "mine"}, {"activity", "visits"},
		{"program_lead", "nobody"}, {"format", "json"}, {"format", "xml"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	return out
}

// teamPlanQuestions are the Team Plan lens's (piece 2): each owner tab (a
// seed officer by StaffProfile id and by User id, one nobody holds), each
// activity family and one the page does not know, every period in each year
// the selector offers, weeks either side of 1 October, months and quarters,
// an advanced filter (blank and set) and a follow-up link.
func teamPlanQuestions() []map[string]string {
	out := []map[string]string{
		{"owner": "team"}, {"owner": "cmw9p7e5q00hglnekhe9h"}, {"owner": "cmw9p7g4j00dkkpekheur"},
		{"owner": "nobody"}, {"owner": "mine", "activity": "trainings"},
		{"activity": "meetings"}, {"activity": "trainings"}, {"activity": "other"},
		{"view": "planning", "period": "week"},
		{"period": "week", "week": "2026-W40"}, {"period": "week", "week": "2025-W10"},
		{"period": "week", "week": "2026-W53"},
		{"period": "month", "month": "10"}, {"period": "month", "month": "3"}, {"month": "6"},
		{"period": "quarter", "quarter": "Q2"}, {"quarter": "Q4"},
		{"district_id": "nowhere"}, {"risk": "any"}, {"followup": "x"},
		// Piece 2 with work: a year with more than a page of visits (its
		// tables page on g1_page-cv and the like, keys the feed drops, so
		// only the first page is asked), an officer's tab, each family,
		// its months (flagged schools) and the planning year's months.
		{"fy": "2026", "owner": "cmw9p7bwp00t19mekheun"}, {"owner": "cmw9p7bwp00t19mekheun"},
		{"fy": "2026", "activity": "meetings"}, {"fy": "2026", "activity": "trainings"}, {"fy": "2026", "activity": "visits"},
		{"fy": "2026", "period": "month", "month": "11"}, {"fy": "2026", "period": "month", "month": "3"},
		{"fy": "2026", "period": "quarter", "quarter": "Q2"}, {"period": "month", "month": "11"},
		{"period": "week", "week": "2026-W45"}, {"period": "week", "week": "2026-W48"},
		// Piece 3, the country lens: each Lead's tab, Unassigned, an
		// officer switch (with work, without, nobody's), in two years.
		{"program_lead": "cmw9p7axf00zhz7ekherr"}, {"program_lead": "cmw9p7b6a00e4s8ekhefr"},
		{"program_lead": "unassigned"}, {"officer": "cmw9p7bwp00t19mekheun"},
		{"officer": "cmw9p7cx800o9ukekheg9"}, {"officer": "nobody"},
		{"fy": "2026", "program_lead": "cmw9p7axf00zhz7ekherr", "officer": "cmw9p7cx800o9ukekheg9"},
		{"fy": "2026", "activity": "meetings", "program_lead": "cmw9p7axf00zhz7ekherr"},
	}
	for _, fy := range []string{"2025", "2027", "2028"} {
		for _, period := range []string{"week", "month", "quarter", "fy"} {
			out = append(out, map[string]string{"fy": fy, "period": period})
		}
	}
	return out
}
