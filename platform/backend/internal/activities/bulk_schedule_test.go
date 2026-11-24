package activities

import (
	"errors"
	"testing"
)

func TestTheBulkScheduleSaysWhatItDid(t *testing.T) {
	tests := []struct {
		scheduled, outside int
		refused            []string
		want               string
	}{
		{1, 0, nil, "Scheduled 1 school."},
		{3, 0, nil, "Scheduled 3 schools."},
		{2, 1, nil, "Scheduled 2 schools. 1 selected school is outside your planning portfolio and left out."},
		{2, 2, []string{"Mpatta: closed", "Kito: full"}, "Scheduled 2 schools. 2 selected schools are outside your planning portfolio and left out. Not scheduled: Mpatta: closed; Kito: full"},
		{0, 0, []string{"Mpatta: closed"}, "Scheduled 0 schools. Not scheduled: Mpatta: closed"},
	}
	for _, tt := range tests {
		if got := bulkScheduledMessage(tt.scheduled, tt.outside, tt.refused); got != tt.want {
			t.Fatalf("got %q\nwant %q", got, tt.want)
		}
	}
}

func TestTheBulkPlanIsReadAsTheExistingPlan(t *testing.T) {
	tests := []struct {
		purpose, course, refusal string
		handOn                   bool
		wantType                 string
	}{
		{"", "", "Select the purpose of the visit before scheduling.", false, ""},
		{"in_school_training", "", "Select the Training to deliver.", false, ""},
		{"in_school_training_ssa", "", "Select the Training to deliver.", false, ""},
		{"in_school_training", "c1", "", true, ""},
		{"in_school_coaching", "", "In-school Coaching Visit is no longer scheduled on its own. Choose In-school Training for this work.", false, ""},
		{"made_up", "", "made_up cannot be assigned to a staff member.", false, ""},
		{"ssa_support", "", "", false, "school_visit_ssa_collection"},
		{"donor_visit", "", "", false, "donor_visit"},
	}
	for _, tt := range tests {
		got, err := bulkPurposeOf(tt.purpose, tt.course)
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
		case err != nil || got.activityType != tt.wantType:
			t.Fatalf("%q: got %+v, %v", tt.purpose, got, err)
		}
	}
	plan, _ := bulkPurposeOf("ssa_support", "")
	if plan.reason != "SSA Support selected by the planner." {
		t.Fatalf("reason %q", plan.reason)
	}
}
