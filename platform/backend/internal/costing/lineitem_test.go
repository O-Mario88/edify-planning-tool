package costing

import "testing"

// The stable category of a budget line (costing_service._line_item_type):
// budget pages and fund requests group and filter by it.
func TestABudgetLineKeepsItsCategory(t *testing.T) {
	tests := map[string]string{
		"activity:X1:Participant transport refund":       "other",
		"school_visit_cost_per_school":                   "school_visit",
		"group_training_participant_meal_cost_per_head":  "participant_meals",
		"tot_trainings_meals":                            "participant_meals",
		"printing_training_materials":                    "materials",
		"photocopying_training_materials":                "materials",
		"core_partner_visit":                             "lump_sum",
		"core_staff_visit":                               "activity_rate",
		"cluster_meeting":                                "activity_rate",
		"proprietor_conference":                          "activity_rate",
		"group_training_venue_cost":                      "venue",
		"group_training_facilitation_fee":                "facilitation",
		"cluster_meeting_participant_meal_cost_per_head": "cluster_meeting_participant_meals",
		"partner_visit_rate":                             "partner_visit",
		"primary_transport_per_day":                      "transport",
		"secondary_transport_per_day":                    "transport",
		"lunch_per_day":                                  "lunch",
		"secondary_lunch_per_day":                        "lunch",
		"secondary_accommodation_per_night":              "accommodation",
		"management_accommodation_per_night":             "accommodation",
		"secondary_overnight_dinner_per_day":             "dinner",
		"secondary_breakfast_per_day":                    "breakfast",
		"secondary_incidentals_per_day":                  "incidentals",
		"airport_transport":                              "transport",
		"dinner":                                         "dinner",
		"venue":                                          "venue",
		"training_session_fee":                           "facilitation",
		"meals_per_participant":                          "participant_meals",
		"mobilisation_per_participant":                   "mobilisation",
		"cluster_meeting_cost":                           "cluster_meeting_participant_meals",
		"some_lump_sum":                                  "lump_sum",
		"anything_else":                                  "other",
	}
	for key, want := range tests {
		t.Run(key, func(t *testing.T) {
			if got := LineItemType(key); got != want {
				t.Fatalf("got %q, want %q", got, want)
			}
		})
	}
}
