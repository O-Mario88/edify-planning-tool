package activities

import (
	"errors"
	"testing"
)

func TestThePlanningAssignFormIsRead(t *testing.T) {
	req, taken := ClientAssignRequestFromValues(" 1045 ", map[string]string{
		"partner_id": " p1 ", "purpose_of_visit": " training_follow_up ", "catalogue_item_id": " c1 ",
		"activity_type": " in_school_training ", "focus_intervention": " leadership ", "source_activity_id": " a1 ",
		"school_id": "1045",
	})
	want := ClientAssignRequest{SchoolCode: "1045", PartnerID: "p1", Purpose: "training_follow_up", ItemID: "c1",
		ActivityType: "in_school_training", Focus: "leadership", SourceActivityID: "a1"}
	if !taken || req != want {
		t.Fatalf("taken %v, got %+v", taken, req)
	}
	if _, taken := ClientAssignRequestFromValues("1045", map[string]string{"project_id": "x"}); taken {
		t.Fatal("a project's hand-over is handed on")
	}
	if _, taken := ClientAssignRequestFromValues("1045", map[string]string{"notes": "", "purpose": ""}); !taken {
		t.Fatal("empty extra fields change nothing")
	}
}

func TestAPartnerIsHandedOnlyAPartnerPurpose(t *testing.T) {
	tests := []struct {
		purpose, activityType, want, refusal string
	}{
		{"ssa_support", "", "ssa_support", ""},
		{"in_school_training", "", "in_school_training", ""},
		{"", "in_school_training", "in_school_training", ""},
		{"", "training_follow_up_visit", "training_follow_up", ""},
		{"", "donor_visit", "ssa_support", ""},
		{"", "", "ssa_support", ""},
		{"donor_visit", "", "", "Donor Visit cannot be assigned to a delivery partner."},
		{"in_school_training_ssa", "", "", "In-school Training + SSA Collection cannot be assigned to a delivery partner."},
		{"made_up", "", "", "made_up cannot be assigned to a delivery partner."},
		{"in_school_coaching", "", "", "In-school Coaching Visit is no longer scheduled on its own. Choose In-school Training for this work."},
	}
	for _, tt := range tests {
		got, err := normalisePartnerPurpose(tt.purpose, tt.activityType)
		var refusal *Refusal
		switch {
		case tt.refusal != "":
			if !errors.As(err, &refusal) || refusal.Message != tt.refusal {
				t.Fatalf("%q: got %q, %v", tt.purpose, got, err)
			}
		case err != nil || got != tt.want:
			t.Fatalf("%q/%q: got %q, %v", tt.purpose, tt.activityType, got, err)
		}
	}
}

func TestTheInterventionFollowsTheItemsMapping(t *testing.T) {
	session := &followedSession{Focus: "", PurposeFocus: "leadership"}
	tests := []struct {
		name      string
		mappings  []mapping
		requested string
		source    *followedSession
		want      string
		refusal   string
	}{
		{"no mapping", nil, "", nil, "", "This Catalogue item has no active intervention mapping."},
		{"any, none named", []mapping{{Mode: "any_ssa_intervention"}}, "", nil, "", ""},
		{"any, named", []mapping{{Mode: "any_ssa_intervention"}}, "leadership", nil, "leadership", ""},
		{"any, not canonical", []mapping{{Mode: "any_ssa_intervention"}}, "nonsense", nil, "", "Choose a valid canonical SSA intervention."},
		{"administrative drops it", []mapping{{Mode: "administrative"}}, "leadership", nil, "", ""},
		{"prerequisite drops it", []mapping{{Mode: "ssa_completion_prerequisite"}}, "leadership", nil, "", ""},
		{"inherit from the session", []mapping{{Mode: "inherit_from_source_activity"}}, "", session, "leadership", ""},
		{"inherit, session has none", []mapping{{Mode: "inherit_from_source_activity"}}, "", &followedSession{}, "",
			"The selected source Activity has no intervention to inherit. Choose a valid source Training or ask IA to repair its mapping."},
		{"inherit, named", []mapping{{Mode: "inherit_from_source_activity"}}, "leadership", nil, "leadership", ""},
		{"inherit, nothing", []mapping{{Mode: "inherit_from_source_activity"}}, "", nil, "",
			"Choose the Training or support Activity being followed up, or select one current unresolved SSA intervention."},
		{"inherit, not canonical", []mapping{{Mode: "inherit_from_source_activity"}}, "nonsense", nil, "", "Choose a valid canonical SSA intervention."},
		{"fixed, primary", []mapping{{Mode: "fixed", Intervention: "leadership", Primary: true}}, "", nil, "leadership", ""},
		{"fixed, planner names another", []mapping{{Mode: "fixed", Intervention: "leadership", Primary: true}}, "teaching_environment", nil, "teaching_environment", ""},
		{"fixed, no primary takes the first sorted", []mapping{{Mode: "fixed", Intervention: "teaching_environment"}, {Mode: "fixed", Intervention: "leadership"}}, "", nil, "leadership", ""},
	}
	for _, tt := range tests {
		got, err := mappedIntervention(tt.mappings, tt.requested, tt.source)
		var refusal *Refusal
		switch {
		case tt.refusal != "":
			if !errors.As(err, &refusal) || refusal.Message != tt.refusal {
				t.Fatalf("%s: got %q, %v", tt.name, got, err)
			}
		case err != nil || got != tt.want:
			t.Fatalf("%s: got %q, %v", tt.name, got, err)
		}
	}
}

func TestAHandOverCommitsTheSchoolByItsShape(t *testing.T) {
	tests := []struct {
		kind, purpose string
		universal     bool
		want          string
	}{
		{"school_visit_ssa_collection", "ssa_support", false, handOverSSASupport},
		{"in_school_training", "in_school_training", true, ""},
		{"in_school_training", "in_school_training", false, handOverVisit},
		{"training_follow_up_visit", "training_follow_up", false, handOverVisit},
	}
	for _, tt := range tests {
		if got := handOverCommitment(tt.kind, tt.purpose, tt.universal); got != tt.want {
			t.Fatalf("%s: got %q", tt.kind, got)
		}
	}
}

func TestThePlanningAssignAnswersInTheExistingWords(t *testing.T) {
	if got, want := clientAssignedMessage("Build Africa"), "Assigned to Build Africa. The partner schedules it from here."; got != want {
		t.Fatalf("got %q", got)
	}
	if got, want := alreadyHandedOver("Mpatta"), "Mpatta already has this work planned, so nothing was added."; got != want {
		t.Fatalf("got %q", got)
	}
	if got, want := clientCourseNotDelivered("Build Africa", "Reading"), "Build Africa is not recorded as delivering Reading. Choose a partner who delivers it, or add it to this partner's activities on their profile."; got != want {
		t.Fatalf("got %q", got)
	}
}
