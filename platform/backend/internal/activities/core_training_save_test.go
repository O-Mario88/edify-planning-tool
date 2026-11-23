package activities

import (
	"net/url"
	"testing"
)

func TestTheCoreTrainingFormIsRead(t *testing.T) {
	req, taken := CoreTrainingRequestFromForm("1045", url.Values{
		"catalogue_item_id": {" c1 "}, "training_number": {"2"}, "scheduled_date": {"2026-12-01"},
		"training_purpose": {" a goal "}, "focus_intervention": {"leadership"}, "facilitating_partner_id": {"p1"},
		"responsible_staff_id": {"s1"}, "recommendation_reason": {"because"}, "expected_participants": {"14"},
		"duration_hours": {"4"}, "delivery_type": {"staff"},
	})
	want := CoreTrainingRequest{SchoolCode: "1045", CourseID: "c1", TrainingNumber: "2", Date: "2026-12-01", Goal: "a goal",
		Focus: "leadership", Facilitator: "p1", Responsible: "s1", RecReason: "because"}
	if !taken || req != want {
		t.Fatalf("taken %v, got %+v", taken, req)
	}
}

func TestACoreTrainingNamingAPartnerIsNotTaken(t *testing.T) {
	if _, taken := CoreTrainingRequestFromForm("1045", url.Values{"assigned_partner_id": {"p1"}}); taken {
		t.Fatal("a partner's training is handed on")
	}
}

func TestTheCoreTrainingFormSaysWhatWasBooked(t *testing.T) {
	if got, want := coreLoneTrainingBooked(2), "Core Training T2 scheduled successfully."; got != want {
		t.Fatalf("got %q", got)
	}
	if got, want := coreLoneUniversalBooked("SSA Training"), "SSA Training scheduled. It is on top of the package's four trainings."; got != want {
		t.Fatalf("got %q", got)
	}
}

func TestALoneCoreTrainingHasNoOutcomeAndNamesNoSlotStaff(t *testing.T) {
	r := activityRow{outcome: "", noOutcomeField: true, responsible: "s1"}
	if r.outcomeValue() != nil {
		t.Fatalf("outcome = %v", r.outcomeValue())
	}
	pl := &plan{row: r, core: &coreBooking{route: corePackageTraining}}
	if slotStaff(pl) != nil {
		t.Fatalf("slot staff = %v", slotStaff(pl))
	}
	visit := &plan{row: activityRow{responsible: "s1"}, core: &coreBooking{route: corePackageVisit}}
	if slotStaff(visit) != "s1" || (activityRow{outcome: "x"}).outcomeValue() != "x" {
		t.Fatal("a visit keeps its staff and outcome")
	}
}
