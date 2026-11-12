package main

import "context"

func init() { pageQuestions["/my-plan"] = myPlanQuestions }

// myPlanQuestions are My Plan's: the page as it opens; each period tab and
// one that is not a period; years in and out of the menu, padded; each
// quarter, a lower-case one and one padded; months, padded, with a quarter
// and with "all"; the week of a month; the form sent back with a wider year
// or quarter (which clears what it held); each filter of the row at a value
// it offers and one it does not; searches; the readiness list key; a key the
// page does not read; and a download's keys, which the feed never passes.
// Values the existing view fails on (a year, month or week that is not a
// whole number or names no day) are left out: the view answers with an
// error, and Go hands those to the existing application.
func myPlanQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"period", "week"}, {"period", "month"}, {"period", "quarter"}, {"period", "fy"},
		{"period", "xyz"}, {"period", " week "},
		{"fy", "2025"}, {"fy", "2026"}, {"fy", "2027"}, {"fy", "2028"}, {"fy", "1999"}, {"fy", " 2026 "},
		{"quarter", "Q1"}, {"quarter", "Q2"}, {"quarter", "Q3"}, {"quarter", "Q4"}, {"quarter", "q3"},
		{"quarter", " Q2 "}, {"quarter", "all"}, {"quarter", "Q9"},
		{"month", "10"}, {"month", "1"}, {"month", "9"}, {"month", " 3 "}, {"month", "all"}, {"month", "ALL"},
		{"week", "1"}, {"week", "4"},
		{"district", "cmw9p55h300a2o1eihgzn"}, {"district", "nope"},
		{"staff", "cmw9p7cfp006nktekheg5"}, {"staff", "nope"},
		{"activity_type", "school_visit"}, {"activity_type", "cluster_training"},
		{"activity_type", "cluster_meeting"}, {"activity_type", "all"}, {"activity_type", "core_visit"},
		{"status", "scheduled"}, {"status", "upcoming"}, {"status", "under_way"}, {"status", "overdue"},
		{"status", "completed"}, {"status", "submitted"}, {"status", "returned_for_correction"},
		{"status", "cancelled"}, {"status", "xyz"},
		{"q", "primary"}, {"q", "zzz"}, {"q", "  Kampala "},
		{"list", "staff_queue"}, {"x", "1"},
		{"export", "xlsx"}, {"format", "readiness-json"}, {"format", "json"}, {"format", "csv"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out,
		map[string]string{"period": "month", "month": "11"},
		map[string]string{"period": "quarter", "quarter": "Q2"},
		map[string]string{"period": "week", "week": "3", "month": "2"},
		map[string]string{"quarter": "Q2", "month": "all"},
		map[string]string{"quarter": "Q2", "month": "5"},
		map[string]string{"fy": "2026", "fy_prev": "2027", "quarter": "Q2", "month": "1"},
		map[string]string{"fy": "2027", "fy_prev": "2027", "quarter": "Q2", "month": "1"},
		map[string]string{"quarter": "Q3", "quarter_prev": "Q2", "month": "5"},
		map[string]string{"quarter": "all", "quarter_prev": "Q1", "month": "4"},
		map[string]string{"fy_prev": "2026", "quarter_prev": "Q4"},
		map[string]string{"fy": "2026", "month": "10", "period": "week", "district": "cmw9p55h300a2o1eihgzn",
			"staff": "cmw9p7cfp006nktekheg5", "activity_type": "cluster_meeting", "status": "completed", "q": "a b"},
	)
	return out
}
