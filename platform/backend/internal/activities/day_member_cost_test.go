package activities

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
)

// A day's re-price keeps a facilitated session's partner fee: the member's
// own lines come from its stored input, which says it is facilitated
// (_costing_input's "facilitated"), as Django's _plan_day prices it.
func TestADaysMemberKeepsItsFacilitationFee(t *testing.T) {
	expected := 14
	in := pricing.Input{Activity: costing.Activity{
		ActivityType: "cluster_meeting", DeliveryType: "staff", Facilitated: true, ExpectedParticipants: &expected,
	}}
	rates := map[string]int64{
		"primary_transport_per_day": 50000, "lunch_per_day": 12000,
		"cluster_meetings_trainings_meals": 5000, "group_training_venue_cost": 30000,
		"group_training_facilitation_fee": 50000,
	}
	cost, err := ownCostOnDay(in, "primary", false, rates, nil)
	if err != nil {
		t.Fatal(err)
	}
	fee := false
	for _, l := range cost.Lines {
		if l.Key == "group_training_facilitation_fee" && l.Amount == 50000 {
			fee = true
		}
	}
	if !fee {
		t.Errorf("the facilitation fee is missing: %+v", cost.Lines)
	}
	in.Facilitated = false
	cost, err = ownCostOnDay(in, "primary", false, rates, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range cost.Lines {
		if l.Key == "group_training_facilitation_fee" {
			t.Errorf("a staff-run meeting carries no fee: %+v", l)
		}
	}
}
