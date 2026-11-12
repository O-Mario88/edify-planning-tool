package main

import "context"

func init() { pageQuestions["/schools/closed"] = closedSchoolsQuestions }

// closedSchoolsQuestions are the archive's: the page as it opens; searches
// that match, match nothing, are padded, are longer than the header shows,
// and carry LIKE's wildcards; the table's page in and out of range and not a
// number; a search and a page together; and a key the page does not read.
func closedSchoolsQuestions(_ context.Context, _ *pageRun, _ string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"q", "church"}, {"q", "CENTRAL DIVISION"}, {"q", "  Primary "}, {"q", "zzz"}, {"q", "%"}, {"q", "_"},
		{"q", "central division church of uganda primary and more"}, {"q", "İstanbul café"},
		{"closed_page", "1"}, {"closed_page", "2"}, {"closed_page", "999"}, {"closed_page", "0"},
		{"closed_page", "-3"}, {"closed_page", "abc"}, {"closed_page", " 2 "},
		{"fy", "2025"}, {"page", "2"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out,
		map[string]string{"q": "a", "closed_page": "2"},
		map[string]string{"q": "primary", "district": "x", "closed_page": "1"})
	return out
}
