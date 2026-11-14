package main

import "context"

func init() { pageQuestions["/staff-activity/people/{id}"] = staffActivityPersonQuestions }

// staffActivityPersonQuestions are a person's detail's (the row the log
// opens): as it opens, every period the log links it with, days in and out
// of them (a weekend, a day to come, the forms date.fromisoformat reads and
// ones it refuses, a year beyond the holiday calendar) and a period not
// offered.
func staffActivityPersonQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, period := range []string{"day", "week", "month", "quarter", "fy", "year"} {
		out = append(out, map[string]string{"period": period})
	}
	for _, on := range []string{"2026-11-13", "2026-11-08", "2026-11-20", "20261110", "2026-W46-1", "garbage", "2025-06-10", "1890-01-01"} {
		out = append(out, map[string]string{"on": on})
	}
	return append(out,
		map[string]string{"period": "week", "on": "2026-11-02"},
		map[string]string{"period": "month", "on": "2026-10-15"},
		map[string]string{"period": "quarter", "on": "2026-08-01"},
		map[string]string{"period": "week", "on": "2026-11-13"},
	)
}
