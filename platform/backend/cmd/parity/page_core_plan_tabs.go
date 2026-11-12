package main

// corePlanTabQuestions are Core School Oversight's two tabs of planned work
// (My Plan's Core School Visits and Core School Trainings rows): each tab
// as it opens, in every year offered and one not offered, with each filter
// that narrows the schools, searches, a sort (which does not reorder the
// plan), pages in and out of range, and a download's keys.
func corePlanTabQuestions() []map[string]string {
	var out []map[string]string
	for _, tab := range []string{"core_visits", "core_trainings"} {
		for _, extra := range []map[string]string{
			{}, {"fy": "2026"}, {"fy": "2025"}, {"fy": "2028"}, {"fy": "1999"},
			{"q": "kimenyedde"}, {"q": "1006"}, {"q": "no such school"},
			{"district": "Mukono"}, {"district": "Nowhere"}, {"type": "champion"}, {"type": "core"},
			{"trajectory": "not_comparable"}, {"attention": "Package incomplete"}, {"readiness": "Not Yet Ready"},
			{"sort": "latest"}, {"page": "2"}, {"page": "999"}, {"page": "abc"},
			{"fy": "2026", "q": "central"}, {"fy": "2026", "page": "2"}, {"fy": "2026", "format": "xlsx"},
		} {
			q := map[string]string{"tab": tab}
			for k, v := range extra {
				q[k] = v
			}
			out = append(out, q)
		}
	}
	return append(out, map[string]string{"tab": " core_visits "}, map[string]string{"tab": "core_trainings", "fy": "2027", "group": "district"})
}
