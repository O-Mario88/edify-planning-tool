package activities

import "testing"

func TestAGovernedSourceNamesTheSSAItRests(t *testing.T) {
	need := schoolNeed{Record: &ssaRecord{ID: "ssa1"}, Ranked: []rankedNeed{{}}}
	got := governedSource("item1", need, true)
	want := map[string]any{
		"engine": "apps.ssa.recommendation_engine", "sourceSsaId": "ssa1", "verificationState": "confirmed",
		"catalogueItemId": "item1", "recommended": true, "projectId": nil, "executorType": "staff", "context": "school",
	}
	for key, value := range want {
		if got[key] != value {
			t.Fatalf("%s = %v, want %v", key, got[key], value)
		}
	}
	if len(got) != len(want) {
		t.Fatalf("got %d keys, want %d: %v", len(got), len(want), got)
	}
}

func TestAGovernedSourceWithoutAnSSASaysSo(t *testing.T) {
	got := governedSource("item1", schoolNeed{}, false)
	if got["sourceSsaId"] != nil || got["verificationState"] != "none" || got["recommended"] != false {
		t.Fatalf("got %v", got)
	}
}

func TestOnlyAFixedBusinessVisitIsTakenAsGoverned(t *testing.T) {
	fixed := item{WorkflowKind: governedVisitKind, Modes: []string{"fixed"}}
	tests := []struct {
		name string
		it   item
		want bool
	}{
		{"a fixed school visit", fixed, true},
		{"standard support", item{WorkflowKind: governedVisitKind, StandardSupport: true, Modes: []string{"fixed"}}, false},
		{"another kind", item{WorkflowKind: "core_visit", Modes: []string{"fixed"}}, false},
		{"inherits its intervention", item{WorkflowKind: governedVisitKind, Modes: []string{"inherit_from_source_activity"}}, false},
		{"two mappings", item{WorkflowKind: governedVisitKind, Modes: []string{"fixed", "fixed"}}, false},
		{"counts toward the client visit", item{WorkflowKind: governedVisitKind, Modes: []string{"fixed"}, CountsTowardClientVisit: true}, false},
		{"priced per participant", item{WorkflowKind: governedVisitKind, Modes: []string{"fixed"}, ParticipantMode: "per_person"}, false},
		{"a training course", item{WorkflowKind: governedVisitKind, Modes: []string{"fixed"}, IsTrainingCourse: true}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := tt.it.governedVisit(); got != tt.want {
				t.Fatalf("governedVisit = %v, want %v", got, tt.want)
			}
		})
	}
}
