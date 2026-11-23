package daypool

import (
	"maps"
	"math"
	"slices"
)

// fallbackWeight is what a type the weights do not list weighs (1.0).
const fallbackWeight = 100

// visitTypes is apps.core.activity_types.VISIT_TYPES.
var visitTypes = []string{
	"school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "donor_visit", "story_gathering_visit",
	"school_invitation", "social_visit", "training_follow_up_visit", "in_school_coaching_visit", "core_visit",
	"core_assessment_visit", "baseline_ssa_visit", "school_visit_ssa_collection", "partner_ssa_collection",
}

// defaultWeights is workload.DEFAULT_WEIGHT_HUNDREDTHS.
var defaultWeights = func() map[string]int {
	weights := map[string]int{}
	for _, activity := range visitTypes {
		weights[activity] = 100
	}
	for _, activity := range []string{"training", "in_school_training", "school_improvement_training", "core_training"} {
		weights[activity] = 250
	}
	for _, activity := range []string{"baseline_ssa_visit", "school_visit_ssa_collection", "ssa_activity",
		"core_assessment_visit", "field_event"} {
		weights[activity] = 150
	}
	weights["cluster_training"], weights["cluster_training_ssa_collection"] = 400, 400
	weights["cluster_meeting"], weights["cluster_meeting_ssa_review"] = 200, 200
	weights["partner_activity"] = 100
	return weights
}()

// DefaultWorkloadWeights is a fresh copy of the spec's weights, in hundredths.
func DefaultWorkloadWeights() map[string]int {
	return maps.Clone(defaultWeights)
}

// MissionAllocation is the day's weighted School Visit Cost Allocation:
// analytics over the pool, never funding. Its figures are nil on a day
// with no visit.
type MissionAllocation struct {
	Allocation, PerSchool  *int64
	TotalUnits, VisitUnits int
	VisitCount             int
	WeightsUsed            map[string]int
}

// AllocateMission is workload.allocate_mission_cost.
func AllocateMission(activityTypes []string, missionCost int64, weights map[string]int) MissionAllocation {
	result := MissionAllocation{WeightsUsed: map[string]int{}}
	for _, activity := range activityTypes {
		weight, listed := weights[activity]
		if !listed {
			weight = fallbackWeight
		}
		result.WeightsUsed[activity] = weight
		result.TotalUnits += weight
		if slices.Contains(visitTypes, activity) {
			result.VisitCount++
			result.VisitUnits += weight
		}
	}
	if result.TotalUnits <= 0 || result.VisitCount == 0 {
		return result
	}
	allocation := roundHalfEven(float64(missionCost*int64(result.VisitUnits)) / float64(result.TotalUnits))
	perSchool := roundHalfEven(float64(allocation) / float64(result.VisitCount))
	result.Allocation, result.PerSchool = &allocation, &perSchool
	return result
}

// roundHalfEven is Python's round.
func roundHalfEven(value float64) int64 {
	return int64(math.RoundToEven(value))
}
