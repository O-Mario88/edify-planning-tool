package costing

import (
	"reflect"
	"testing"
)

func card(pairs ...any) map[string]int64 {
	c := map[string]int64{}
	for i := 0; i < len(pairs); i += 2 {
		c[pairs[i].(string)] = int64(pairs[i+1].(int))
	}
	return c
}

func keysOf(c Cost) []string {
	out := []string{}
	for _, l := range c.Lines {
		out = append(out, l.Key)
	}
	return out
}

func intp(n int) *int { return &n }

var dayCard = card(
	"primary_transport_per_day", 10000, "secondary_transport_per_day", 30000,
	"lunch_per_day", 15000, "secondary_breakfast_per_day", 8000,
	"secondary_overnight_dinner_per_day", 12000, "secondary_accommodation_per_night", 50000,
	"management_accommodation_per_night", 90000,
)

func TestAPrimaryStaffVisitIsTransportAndLunch(t *testing.T) {
	c := CostForActivity(Activity{ActivityType: "school_visit", DistrictType: "primary"}, dayCard)
	if got, want := keysOf(c), []string{"primary_transport_per_day", "lunch_per_day"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("keys %v, want %v", got, want)
	}
	if c.Amount != 25000 || c.CostMissing {
		t.Fatalf("amount %d missing %v", c.Amount, c.CostMissing)
	}
}

func TestASecondaryVisitNightIsAtTheTravellersRateAndTheReturnDayHasNone(t *testing.T) {
	away := CostForActivity(Activity{ActivityType: "school_visit", DistrictType: "secondary", AccommodationKey: "management_accommodation_per_night"}, dayCard)
	if away.Amount != 30000+15000+8000+12000+90000 {
		t.Fatalf("a night away at the management rate: %d (%v)", away.Amount, keysOf(away))
	}
	home := CostForActivity(Activity{ActivityType: "school_visit", DistrictType: "secondary", ReturnDay: true}, dayCard)
	if got, want := keysOf(home), []string{"secondary_transport_per_day", "lunch_per_day", "secondary_breakfast_per_day"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("return day keys %v, want %v", got, want)
	}
	unknown := CostForActivity(Activity{ActivityType: "school_visit", DistrictType: "secondary", AccommodationKey: "lunch_per_day"}, dayCard)
	if unknown.Amount != 30000+15000+8000+12000+50000 {
		t.Fatalf("an unknown night rate prices the CCEO's: %d", unknown.Amount)
	}
}

func TestAPartnerVisitIsThePartnersRateAlone(t *testing.T) {
	c := CostForActivity(Activity{ActivityType: "core_visit", DeliveryType: "partner"}, card("core_partner_visit", 70000, "client_partner_visit", 60000))
	if len(c.Lines) != 1 || c.Lines[0].Label != "Core Partner Visit [Rate basis: per activity]" || c.Amount != 70000 {
		t.Fatalf("lines %+v", c.Lines)
	}
}

func TestAMeetingWithNoHeadcountIsUnfundable(t *testing.T) {
	c := CostForActivity(Activity{ActivityType: "cluster_meeting"}, card("cluster_meetings_trainings_meals", 5000, "group_training_venue_cost", 1))
	if !c.CostMissing || c.MissingItems[len(c.MissingItems)-1] != "expectedParticipants" {
		t.Fatalf("missing %v %v", c.CostMissing, c.MissingItems)
	}
	fed := CostForActivity(Activity{ActivityType: "cluster_meeting", ExpectedParticipants: intp(20)}, card("cluster_meetings_trainings_meals", 5000))
	if fed.Lines[0].Qty != 20 || fed.Lines[0].Amount != 100000 {
		t.Fatalf("meals %+v", fed.Lines[0])
	}
}

func TestAMissingRequiredRateIsNamedAndAMissingAddedRateIsSkipped(t *testing.T) {
	c := CostForActivity(Activity{ActivityType: "school_visit", CostingKind: "onetest"}, card("lunch_per_day", 15000))
	if got, want := c.MissingItems, []string{"primary_transport_per_day"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("missing %v, want %v (OneTest is an added rate and is skipped)", got, want)
	}
}

func TestARenamedKeyAnswersForTheNewOne(t *testing.T) {
	c := CostForActivity(Activity{ActivityType: "school_visit"}, card("primary_transport_per_day", 1, "primary_lunch_per_day", 4))
	if c.CostMissing || c.Amount != 5 {
		t.Fatalf("amount %d missing %v", c.Amount, c.MissingItems)
	}
}

func TestTheRulesCompile(t *testing.T) {
	if _, err := compile(rulesJSON); err != nil {
		t.Fatal(err)
	}
	if _, err := compile([]byte(`{"day":{"required":{}}}`)); err == nil {
		t.Fatal("rules without a day compiled")
	}
}
