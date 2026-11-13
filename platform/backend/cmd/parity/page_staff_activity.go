package main

import "context"

func init() { pageQuestions["/staff-activity"] = staffActivityQuestions }

// staffActivityQuestions are the Staff Activity Log's: the log as it opens;
// every period, days in and out of it (a weekend, a day to come, the forms
// date.fromisoformat reads and ones it refuses, a year beyond the holiday
// calendar); every role and status; searches; the table's page in and out of
// range; filters together; and every Programme Lead the page offers.
func staffActivityQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"period", "day"}, {"period", "week"}, {"period", "month"}, {"period", "quarter"}, {"period", "fy"},
		{"period", "year"}, {"period", " week"},
		{"on", "2026-11-12"}, {"on", "2026-11-01"}, {"on", "2026-11-20"}, {"on", " 20261111 "}, {"on", "2026-W46-1"},
		{"on", "garbage"}, {"on", "2026-02-30"}, {"on", "2025-12-25"}, {"on", "1890-01-01"},
		{"role", "CCEO"}, {"role", "Program Lead"}, {"role", "Admin"}, {"role", " CCEO "},
		{"status", "online"}, {"status", "idle"}, {"status", "offline"}, {"status", "no_login"},
		{"status", "on_leave"}, {"status", "follow_up"}, {"status", "nonsense"},
		{"q", "paul"}, {"q", "PROGRAM"}, {"q", "zzz"}, {"q", "%"}, {"q", " ruth "},
		{"staff_page", "2"}, {"staff_page", "abc"}, {"pl", "nobody"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out,
		map[string]string{"period": "week", "on": "2026-11-05"},
		map[string]string{"period": "month", "on": "2026-10-15"},
		map[string]string{"period": "quarter", "on": "2026-08-01"},
		map[string]string{"period": "week", "role": "CCEO", "status": "follow_up"},
		map[string]string{"period": "fy", "fy": "2026"},
		// A day long past, which the development data leaves quiet unless a
		// day is filed there (docs/migration/41-staff-activity.md).
		map[string]string{"on": "2025-06-10"},
		map[string]string{"on": "2025-06-10", "q": "paul"},
		map[string]string{"on": "2025-06-10", "status": "follow_up"},
		map[string]string{"on": "2025-06-10", "role": "CCEO", "pl": "nobody"},
		map[string]string{"on": "2025-06-10", "period": "week"},
		map[string]string{"on": "2025-06-10", "period": "month"},
	)
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			if f.GetName() != "pl" {
				continue
			}
			for _, o := range f.GetOptions() {
				if o.GetValue() != "" {
					out = append(out, map[string]string{"pl": o.GetValue()})
				}
			}
		}
	}
	return out
}
