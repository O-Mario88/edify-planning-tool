package daypool

import "testing"

// A day of two visits and two trainings: the visits carry their weight of the
// mission, never the whole of it.
func TestTheDaysVisitsCarryOnlyTheirShare(t *testing.T) {
	got := AllocateMission([]string{"core_visit", "in_school_training", "core_visit", "in_school_training"}, 62000, DefaultWorkloadWeights())
	if got.Allocation == nil || *got.Allocation != 17714 || got.PerSchool == nil || *got.PerSchool != 8857 {
		t.Fatalf("got %+v", got)
	}
	if got.TotalUnits != 700 || got.VisitUnits != 200 || got.VisitCount != 2 {
		t.Fatalf("got %+v", got)
	}
	if got.WeightsUsed["core_visit"] != 100 || got.WeightsUsed["in_school_training"] != 250 {
		t.Fatalf("weights %+v", got.WeightsUsed)
	}
}

func TestADayWithoutAVisitHasNoVisitAllocation(t *testing.T) {
	got := AllocateMission([]string{"in_school_training"}, 62000, DefaultWorkloadWeights())
	if got.Allocation != nil || got.PerSchool != nil || got.TotalUnits != 250 || got.VisitCount != 0 {
		t.Fatalf("got %+v", got)
	}
}

func TestAConfiguredWeightOverridesTheDefault(t *testing.T) {
	weights := DefaultWorkloadWeights()
	weights["in_school_training"] = 100
	got := AllocateMission([]string{"core_visit", "in_school_training"}, 1000, weights)
	if got.Allocation == nil || *got.Allocation != 500 {
		t.Fatalf("got %+v", got)
	}
}

func TestAnUnlistedTypeWeighsOne(t *testing.T) {
	got := AllocateMission([]string{"core_visit", "something_new"}, 1000, DefaultWorkloadWeights())
	if got.TotalUnits != 200 || got.WeightsUsed["something_new"] != 100 {
		t.Fatalf("got %+v", got)
	}
}

// Python's round: half goes to the even neighbour.
func TestTheAllocationRoundsLikeTheExistingOne(t *testing.T) {
	weights := map[string]int{"core_visit": 100, "training": 300}
	got := AllocateMission([]string{"core_visit", "training"}, 10, weights) // 2.5
	if got.Allocation == nil || *got.Allocation != 2 {
		t.Fatalf("got %+v", got)
	}
}

func TestDefaultWeightsFollowTheSpec(t *testing.T) {
	weights := DefaultWorkloadWeights()
	for activity, want := range map[string]int{
		"school_visit": 100, "core_visit": 100, "baseline_ssa_visit": 150, "school_visit_ssa_collection": 150,
		"ssa_activity": 150, "core_assessment_visit": 150, "training": 250, "core_training": 250,
		"cluster_training": 400, "cluster_training_ssa_collection": 400, "cluster_meeting": 200,
		"cluster_meeting_ssa_review": 200, "field_event": 150, "partner_activity": 100,
	} {
		if weights[activity] != want {
			t.Fatalf("%s = %d, want %d", activity, weights[activity], want)
		}
	}
}
