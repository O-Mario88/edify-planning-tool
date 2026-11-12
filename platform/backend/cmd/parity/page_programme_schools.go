package main

import "context"

func init() { pageQuestions["/programme-schools"] = programmeSchoolsQuestions }

// programmeSchoolsQuestions are the Programme Schools page's: the page as
// it opens; each school type and one that is not a type; every year offered
// and one that is not; searches by name and by School ID, matching nothing,
// padded, with LIKE's wildcards and longer than the header shows; the
// table's page in and out of range; filters together; and the districts the
// listed schools are in, with one that holds none and one that is not a
// district.
func programmeSchoolsQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"school_type", "champion"}, {"school_type", "core_trained"}, {"school_type", "core_graduate"},
		{"school_type", "client"}, {"school_type", "nonsense"},
		{"fy", "2025"}, {"fy", "2026"}, {"fy", "2027"}, {"fy", "2028"}, {"fy", "1999"},
		{"q", "primary"}, {"q", "GOMA"}, {"q", "15"}, {"q", "  hill "}, {"q", "zzz"}, {"q", "%"}, {"q", "_"},
		{"q", "goma division church of uganda primary and more"},
		{"programme_page", "2"}, {"programme_page", "0"}, {"programme_page", "abc"},
		{"district", "nonsense"}, {"page", "2"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out,
		map[string]string{"q": "primary", "school_type": "champion"},
		map[string]string{"q": "primary", "school_type": "core_trained", "fy": "2026"},
		map[string]string{"school_type": "champion", "fy": "2026", "programme_page": "2"})
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			if f.GetName() != "district" {
				continue
			}
			for i, o := range f.GetOptions() {
				// The first district offered, and Mukono, where the seed's schools are.
				if o.GetValue() != "" && (i == 1 || o.GetLabel() == "Mukono") {
					out = append(out,
						map[string]string{"district": o.GetValue()},
						map[string]string{"district": o.GetValue(), "school_type": "champion", "q": "hill"})
				}
			}
		}
	}
	return out
}
