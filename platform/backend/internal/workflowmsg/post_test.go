package workflowmsg

import (
	"strings"
	"testing"
)

// The bell's preview is _notify_recipient's: the body stripped, and past
// 120 characters its first 117 and an ellipsis.
func TestPreviewIsTheExistingPreview(t *testing.T) {
	long := strings.Repeat("é", 130)
	for _, c := range []struct{ in, want string }{
		{"  Please date it \n", "Please date it"},
		{strings.Repeat("a", 120), strings.Repeat("a", 120)},
		{long, strings.Repeat("é", 117) + "…"},
		{" x　", "x"},
	} {
		if got := Preview(c.in); got != c.want {
			t.Errorf("Preview(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

// Recipients are each made a participant once, empty ids dropped, in the
// order given.
func TestUniqueKeepsOrderAndDropsEmpties(t *testing.T) {
	got := unique([]string{"b", "", "a", "b"})
	if strings.Join(got, ",") != "b,a" {
		t.Fatalf("unique = %v", got)
	}
	if FallbackLabel("School", "s1") != "School s1" {
		t.Fatalf("label %q", FallbackLabel("School", "s1"))
	}
}
