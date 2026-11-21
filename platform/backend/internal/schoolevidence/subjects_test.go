package schoolevidence

import (
	"reflect"
	"testing"
)

// Subjects that differ only in case come out in one order every time, the
// existing page's (sorted by str.lower, then the subject itself): the
// database's DISTINCT order and Python's set order are not stable.
func TestSubjectsSortCaseBlindThenExactly(t *testing.T) {
	for _, in := range [][]string{
		{"english", "Maths", "English", "art"},
		{"English", "art", "english", "Maths"},
	} {
		got := append([]string{}, in...)
		sortSubjects(got)
		want := []string{"art", "English", "english", "Maths"}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("sortSubjects(%q) = %q, want %q", in, got, want)
		}
	}
}
