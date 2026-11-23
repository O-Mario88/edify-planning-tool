package activities

import "testing"

func slotTaken(status string) bool {
	return status == "Scheduled" || status == "scheduled" || status == "Assigned" || status == "completed"
}

func TestAPackageVisitTakesTheLowestOpenSlot(t *testing.T) {
	tests := []struct {
		name  string
		slots []coreSlot
		want  string
	}{
		{"the first when all are open", []coreSlot{{ID: "v1", Status: "Planned"}, {ID: "v2", Status: "Planned"}}, "v1"},
		{"past a scheduled one", []coreSlot{{ID: "v1", Status: "Scheduled"}, {ID: "v2", Status: "Planned"}}, "v2"},
		{"past one a partner holds", []coreSlot{{ID: "v1", Status: "Assigned"}, {ID: "v2", Status: "Planned"}}, "v2"},
		{"none left", []coreSlot{{ID: "v1", Status: "completed"}, {ID: "v2", Status: "Scheduled"}}, ""},
		{"no slots", nil, ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := openCoreSlot(tt.slots, slotTaken)
			if (got == nil) != (tt.want == "") || (got != nil && got.ID != tt.want) {
				t.Fatalf("got %+v, want %q", got, tt.want)
			}
		})
	}
}

func TestAFullStaffHalfSaysWhoseVisitIsNext(t *testing.T) {
	want := "Mpatta already has its 2 staff core visits (2/2). A Core package is 2 staff and 2 partner visits, so the next visit here is the partner's."
	if got := coreStaffSideRefusal("Mpatta", 2); got != want {
		t.Fatalf("got %q", got)
	}
}

func TestOnlyTheCoreFollowUpItemIsACoreVisit(t *testing.T) {
	core := item{WorkflowKind: coreVisitKind, Modes: []string{inheritMappingMode}}
	if !core.coreVisit() {
		t.Fatal("the Core School follow-up item is a core visit")
	}
	for name, it := range map[string]item{
		"standard":     {WorkflowKind: coreVisitKind, StandardSupport: true, Modes: []string{inheritMappingMode}},
		"another kind": {WorkflowKind: "school_visit", Modes: []string{inheritMappingMode}},
		"fixed":        {WorkflowKind: coreVisitKind, Modes: []string{"fixed"}},
		"per person":   {WorkflowKind: coreVisitKind, Modes: []string{inheritMappingMode}, ParticipantMode: "per_person"},
	} {
		if it.coreVisit() {
			t.Fatalf("%s is not the core visit", name)
		}
	}
}

func TestOnlyPackagePurposesTakeTheCoreRoute(t *testing.T) {
	for purpose, want := range map[string]coreRoute{
		"training_follow_up": corePackageVisit, "ssa_support": coreCreditedVisit,
		"donor_visit": coreOutsidePackage, "story_gathering": coreOutsidePackage,
		"school_invitation": coreOutsidePackage, "social_visit": coreOutsidePackage,
	} {
		if got := coreRouteFor(purpose); got != want {
			t.Fatalf("%s = %v, want %v", purpose, got, want)
		}
	}
}

func TestAPackageVisitIsCorePlanning(t *testing.T) {
	r := newRow(rowInput{activityType: coreVisitKind})
	if source, context := r.planning(); source != "core_planning" || context != "school" {
		t.Fatalf("planning = %q %q", source, context)
	}
	r = newRow(rowInput{activityType: "donor_visit"})
	if source, context := r.planning(); source != "school_planning" || context != "school" {
		t.Fatalf("planning = %q %q", source, context)
	}
}
