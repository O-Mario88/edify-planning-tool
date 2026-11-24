package activities

import (
	"errors"
	"testing"
)

func TestTheBulkHandOverSaysWhatItDid(t *testing.T) {
	tests := []struct {
		count, skipped int
		gated          []string
		want           string
	}{
		{1, 0, nil, "Assigned 1 school to Build Africa."},
		{2, 1, nil, "Assigned 2 schools to Build Africa. 1 was already waiting with this partner and left as they were."},
		{0, 2, nil, "Assigned 0 schools to Build Africa. 2 were already waiting with this partner and left as they were."},
		{1, 0, []string{"Mpatta", "Kito (ssa completed this year)"},
			"Assigned 1 school to Build Africa. Not assigned (their support is not open to a partner now): Mpatta, Kito (ssa completed this year)."},
	}
	for _, tt := range tests {
		if got := bulkAssignedMessage(tt.count, "Build Africa", tt.skipped, tt.gated); got != tt.want {
			t.Fatalf("got %q\nwant %q", got, tt.want)
		}
	}
}

func TestTheBulkHandOverReadsItsReason(t *testing.T) {
	tests := []struct {
		purpose, course, refusal string
		handOn                   bool
	}{
		{"", "", "Select the reason for assigning before confirming.", false},
		{"donor_visit", "", "Donor Visit cannot be assigned to a delivery partner.", false},
		{"in_school_training", "", "Select the Training the partner delivers.", false},
		{"in_school_training", "c1", "", true},
		{"ssa_support", "", "", false},
	}
	for _, tt := range tests {
		_, err := bulkHandOverPurpose(tt.purpose, tt.course)
		var refusal *Refusal
		switch {
		case tt.handOn:
			if !errors.Is(err, ErrHandOn) {
				t.Fatalf("%q: want hand-on, got %v", tt.purpose, err)
			}
		case tt.refusal != "":
			if !errors.As(err, &refusal) || refusal.Message != tt.refusal {
				t.Fatalf("%q: got %v", tt.purpose, err)
			}
		case err != nil:
			t.Fatalf("%q: %v", tt.purpose, err)
		}
	}
}

func TestARefusedSchoolIsNamedWithItsReason(t *testing.T) {
	if got := gatedName("Kito", &Refusal{Message: "x", Label: "ssa completed this year"}); got != "Kito (ssa completed this year)" {
		t.Fatalf("got %q", got)
	}
	if got := gatedName("Kito", &Refusal{Message: "x"}); got != "Kito" {
		t.Fatalf("got %q", got)
	}
}
