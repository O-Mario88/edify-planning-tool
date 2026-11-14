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
	return append(out, byStaffAndSchoolsQuestions(leads)...)
}

// byStaffAndSchoolsQuestions are the By staff and Schools tabs: each tab
// spelt with stray spaces and capitals, other years, each Lead's team, the
// tables' pages in and out of range; on Schools every training committed and
// one that is not, a staff member, a Lead and someone unknown, every Show
// value and one that is not, and those together.
func byStaffAndSchoolsQuestions(leads []string) []map[string]string {
	trainings := []string{"cmw9p6zjg00u2wieihg9o", "cmw9p6zpe00r0kxeihgq6", "cmw9p6zg600734ueihg0f", "nonsense"}
	q := func(pairs ...string) map[string]string {
		m := map[string]string{"view": "trainings"}
		for i := 0; i+1 < len(pairs); i += 2 {
			m[pairs[i]] = pairs[i+1]
		}
		return m
	}
	out := []map[string]string{
		q("tab", "staff"), q("tab", " STAFF "), q("tab", "staff", "fy", "2026"), q("tab", "staff", "fy", "2028"),
		q("tab", "staff", "by_staff_page", "2"), q("tab", "staff", "by_staff_page", "0"), q("tab", "staff", "by_staff_page", "x"),
		q("tab", "schools"), q("tab", " Schools "), q("tab", "schools", "fy", "2026"), q("tab", "schools", "fy", "2028"),
		q("tab", "schools", "coverage_page", "3"), q("tab", "schools", "staff", "cmw9p7bwp00t19mekheun"),
		q("tab", "schools", "staff", leads[0]), q("tab", "schools", "staff", "nobody"),
		q("tab", "schools", "staff", " cmw9p7bwp00t19mekheun "),
		q("tab", "schools", "training", trainings[2], "staff", "cmw9p7bwp00t19mekheun", "show", "remaining"),
		q("tab", "schools", "program_lead", leads[0], "training", trainings[2]),
		q("tab", "schools", "training", trainings[2], "coverage_page", "2"),
		q("tab", "schools", "training", trainings[2], "coverage_page", "7"),
		q("tab", "schools", "training", trainings[2], "coverage_page", "14"),
		q("tab", "schools", "training", trainings[2], "coverage_page", "99", "fy", "2028"),
		q("tab", "schools", "training", trainings[0], "show", "remaining", "coverage_page", " 3 "),
	}
	for _, lead := range leads {
		out = append(out, q("tab", "staff", "program_lead", lead), q("tab", "schools", "program_lead", lead))
	}
	for _, training := range trainings {
		out = append(out, q("tab", "schools", "training", training), q("tab", "schools", "training", training, "show", "remaining"))
	}
	for _, show := range []string{"covered", "staff", "partner", "partner_scheduled", "awaiting", "group", "in_progress", "completed", "remaining", "bogus"} {
		out = append(out, q("tab", "schools", "show", show))
	}
	return out
}
