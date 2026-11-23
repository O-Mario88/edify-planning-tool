package coreforms

import "testing"

func TestAGovernedItemTakesItsReasonFromTheRecommendation(t *testing.T) {
	all := []Suggestion{
		{ID: "a", Reason: "Leadership is Critical at 3.0/10."},
		{ID: "b", Reason: "Enrolment is Warning at 5.0/10."},
		{ID: "c", Reason: "Finance is Warning at 5.5/10."},
		{ID: "d", Reason: "Teaching is Good at 7.0/10."},
	}
	tests := []struct {
		name, item, reason string
		recommended        bool
	}{
		{"first", "a", "Leadership is Critical at 3.0/10.", true},
		{"third is still primary", "c", "Finance is Warning at 5.5/10.", true},
		{"fourth is an eligible alternative", "d", "Teaching is Good at 7.0/10.", false},
		{"not offered at all", "z", "Authorized alternative Catalogue Activity.", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			reason, recommended := governedWord(all, tt.item)
			if reason != tt.reason || recommended != tt.recommended {
				t.Fatalf("got %q %v, want %q %v", reason, recommended, tt.reason, tt.recommended)
			}
		})
	}
}

func TestAnEmptyRecommendationCallsTheItemAnAlternative(t *testing.T) {
	reason, recommended := governedWord(nil, "a")
	if reason != "Authorized alternative Catalogue Activity." || recommended {
		t.Fatalf("got %q %v", reason, recommended)
	}
}
