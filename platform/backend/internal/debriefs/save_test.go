package debriefs

import (
	"slices"
	"testing"
	"time"
)

// The form's work: a checklist joined by commas, or the one box's "on".
func TestTheFormsWorkIsReadAsOneList(t *testing.T) {
	if got := ActivityIDs("a1, a2,,a3"); !slices.Equal(got, []string{"a1", "a2", "a3"}) {
		t.Fatalf("got %v", got)
	}
	if got := ActivityIDs(""); len(got) != 0 {
		t.Fatalf("got %v", got)
	}
}

// get_operational_fy: October opens the next financial year.
func TestADebriefIsFiledUnderTheOperationalYear(t *testing.T) {
	for at, want := range map[string]string{"2026-09-30": "2026", "2026-10-01": "2027", "2027-01-15": "2027"} {
		day, _ := time.Parse(time.DateOnly, at)
		if got := operationalFY(day); got != want {
			t.Fatalf("%s = %s, want %s", at, got, want)
		}
	}
}
