package programmerollout

import (
	"testing"
	"time"
)

func TestRolloutDayIsDjangosFormat(t *testing.T) {
	d := time.Date(2026, 3, 5, 0, 0, 0, 0, time.UTC)
	if got := rolloutDay(&d); got != "5 Mar 2026" {
		t.Errorf("rolloutDay = %q", got)
	}
	if got := rolloutDay(nil); got != "" {
		t.Errorf("no day = %q", got)
	}
}

func TestFactWordsAreTheServices(t *testing.T) {
	d := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	cases := []struct{ got, want string }{
		{collectionFact("scheduled", &d, ""), "Collection scheduled 20 Nov 2026"},
		{collectionFact("partner_scheduled", &d, "Literacy Uganda"), "Collection partner scheduled 20 Nov 2026 with Literacy Uganda"},
		{collectionFact("planned", nil, ""), "Collection planned"},
		{heldFact("completed", &d), "Collection held 20 Nov 2026, completed"},
		{heldFact("submitted_to_pl", nil), "Collection held, submitted to pl"},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("got %q, want %q", c.got, c.want)
		}
	}
}

func TestStateOfIsTheFirstQualifyingState(t *testing.T) {
	d := time.Date(2026, 1, 9, 0, 0, 0, 0, time.UTC)
	if s := stateOf(true, &d, nil, []string{"x"}); s.state != stateConfirmed || s.detail != "Confirmed 9 Jan 2026" {
		t.Errorf("confirmed = %+v", s)
	}
	if s := stateOf(false, nil, []string{"Uploaded 1 Feb 2026, not yet verified", "later"}, []string{"x"}); s.state != stateAwaiting || s.detail != "Uploaded 1 Feb 2026, not yet verified" {
		t.Errorf("awaiting = %+v", s)
	}
	if s := stateOf(false, nil, nil, []string{"Handed to P, not yet scheduled"}); s.state != stateScheduled || s.detail != "Handed to P, not yet scheduled" {
		t.Errorf("scheduled = %+v", s)
	}
	if s := stateOf(true, nil, nil, nil); s.detail != "Confirmed" {
		t.Errorf("undated confirmed = %+v", s)
	}
	if s := stateOf(false, nil, nil, nil); s.state != stateNotPlanned || s.detail != "No SSA collection planned this FY" {
		t.Errorf("not planned = %+v", s)
	}
}

func TestCountLineSaysWhenItIsCut(t *testing.T) {
	if got := countLine(1, 1); got != "1 school" {
		t.Errorf("one = %q", got)
	}
	if got := countLine(3, 3); got != "3 schools" {
		t.Errorf("three = %q", got)
	}
	if got := countLine(250, 200); got != "250 schools, the first 200 shown" {
		t.Errorf("cut = %q", got)
	}
}
