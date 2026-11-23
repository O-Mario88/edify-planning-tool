package costing

import (
	"slices"
	"strings"
)

// LineItemType is costing_service._line_item_type: the stable category of a
// budget line. Budget pages and fund requests group and filter by it.
func LineItemType(key string) string {
	if strings.HasPrefix(key, "activity:") {
		return "other" // A cost the CD added is never typed by the words in it.
	}
	if strings.Contains(key, "school_visit_cost_per_school") {
		return "school_visit"
	}
	for _, group := range lineItemGroups {
		if slices.Contains(group.keys, key) {
			return group.category
		}
	}
	switch {
	case strings.Contains(key, "transport"):
		return "transport"
	case key == "breakfast", key == "lunch", key == "dinner", key == "accommodation":
		return key
	case key == "venue":
		return "venue"
	case key == "training_session_fee":
		return "facilitation"
	case key == "meals_per_participant":
		return "participant_meals"
	case key == "mobilisation_per_participant":
		return "mobilisation"
	case key == "cluster_meeting_cost":
		return "cluster_meeting_participant_meals"
	case strings.Contains(key, "lump_sum"):
		return "lump_sum"
	}
	return "other"
}

// lineItemGroups are the exact keys, checked before the looser matches.
var lineItemGroups = []struct {
	category string
	keys     []string
}{
	{"participant_meals", []string{"group_training_participant_meal_cost_per_head", "tot_trainings_meals",
		"cluster_meetings_trainings_meals", "group_training_meals"}},
	{"materials", []string{"printing_training_materials", "photocopying_training_materials"}},
	{"lump_sum", []string{"client_partner_visit", "core_partner_visit", "partner_meetings"}},
	{"activity_rate", []string{"client_staff_visit", "core_staff_visit", "ssa_support", "onetest",
		"cluster_meetings_trainings", "cluster_meeting", "tot_trainings", "student_conference", "proprietor_conference"}},
	{"venue", []string{"group_training_venue_cost"}},
	{"facilitation", []string{"group_training_facilitation_fee"}},
	{"cluster_meeting_participant_meals", []string{"cluster_meeting_participant_meal_cost_per_head"}},
	{"partner_visit", []string{"partner_visit_rate"}},
	{"transport", []string{"primary_transport_per_day", "secondary_transport_per_day"}},
	{"lunch", []string{"primary_lunch_per_day", "secondary_lunch_per_day", "lunch_per_day"}},
	{"accommodation", []string{"secondary_accommodation_per_night", "management_accommodation_per_night"}},
	{"dinner", []string{"secondary_overnight_dinner_per_day"}},
	{"breakfast", []string{"secondary_breakfast_per_day"}},
	{"incidentals", []string{"secondary_incidentals_per_day"}},
}
