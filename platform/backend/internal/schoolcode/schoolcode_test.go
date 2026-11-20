package schoolcode

import "testing"

// A reference reads as the middleware fills it in: a found school's ID,
// else "ID unavailable" (a deleted school, a school with no ID, no school).
func TestOfIsTheWebsFilledInID(t *testing.T) {
	codes := Codes{"cuid1": "1599", "1599": "1599", "cuid2": ""}
	for ref, want := range map[string]string{
		"cuid1":   "1599",
		"1599":    "1599",
		"cuid2":   Unavailable,
		"missing": Unavailable,
	} {
		if got := codes.Of(ref); got != want {
			t.Errorf("Of(%q) = %q, want %q", ref, got, want)
		}
	}
}
