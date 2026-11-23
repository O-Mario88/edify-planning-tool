package activities

import (
	"net/url"
	"testing"
)

func TestTheCoreVisitFormIsReadWithItsSlotAndPeople(t *testing.T) {
	req, taken := CoreVisitRequestFromForm("1045", url.Values{
		"purpose_of_visit": {" training_follow_up "}, "scheduled_date": {"2026-12-01"}, "visit_number": {"2"},
		"focus_intervention": {"leadership"}, "responsible_staff_id": {"s1"}, "source_activity_id": {"a1"},
		"activity_goal": {" a goal "}, "expected_outcome": {" an outcome "}, "visit_justification": {" why "},
		"training_course_id": {"c1"}, "training_number": {"3"}, "recommendation_reason": {"because"},
	})
	if !taken {
		t.Fatal("the form should be taken")
	}
	want := CoreVisitRequest{
		SchoolCode: "1045", Purpose: "training_follow_up", Date: "2026-12-01", VisitNumber: "2",
		Focus: "leadership", Responsible: "s1", SourceActivityID: "a1", Goal: "a goal", Outcome: "an outcome",
		Justification: "why", TrainingCourseID: "c1", TrainingNumber: "3", RecReason: "because",
	}
	if req != want {
		t.Fatalf("got %+v", req)
	}
}

// The view reads who delivers from the partner it is given, never from this
// field, which the form always posts.
func TestTheCoreVisitFormsDeliveryFieldChangesNothing(t *testing.T) {
	if _, taken := CoreVisitRequestFromForm("1045", url.Values{"delivery_type": {"staff"}}); !taken {
		t.Fatal("the form always posts its delivery type")
	}
}

func TestTheCoreVisitFormFallsBackToItsOlderGoalField(t *testing.T) {
	req, taken := CoreVisitRequestFromForm("1045", url.Values{"visit_purpose": {"an older goal"}})
	if !taken || req.Goal != "an older goal" {
		t.Fatalf("taken %v, goal %q", taken, req.Goal)
	}
}

func TestACoreVisitNamingAPartnerOrItemIsNotTaken(t *testing.T) {
	for _, field := range []string{"assigned_partner_id", "catalogue_item_id", "project_id"} {
		if _, taken := CoreVisitRequestFromForm("1045", url.Values{field: {"x"}}); taken {
			t.Fatalf("%s must be handed on", field)
		}
		if _, taken := CoreVisitRequestFromForm("1045", url.Values{field: {" "}}); !taken {
			t.Fatalf("a blank %s changes nothing", field)
		}
	}
}

func TestTheChosenSlotIsTakenWhenItIsOpen(t *testing.T) {
	slots := []coreSlot{
		{ID: "v1", Sequence: 1, Status: "Scheduled"}, {ID: "v2", Sequence: 2, Status: "Planned"},
		{ID: "v3", Sequence: 3, Status: "Planned"},
	}
	tests := []struct {
		name      string
		preferred int
		want      string
	}{
		{"an open slot", 3, "v3"},
		{"a taken slot falls to the next open", 1, "v2"},
		{"no preference", 0, "v2"},
		{"a slot that does not exist", 9, "v2"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := openCoreSlotAt(slots, tt.preferred, slotTaken)
			if got == nil || got.ID != tt.want {
				t.Fatalf("got %+v, want %s", got, tt.want)
			}
		})
	}
}

func TestACoreVisitSlotNumberIsWholeOrOne(t *testing.T) {
	for raw, want := range map[string]int{"": 1, "3": 3} {
		got, err := coreSlotNumber(raw)
		if err != nil || got != want {
			t.Fatalf("%q = %d, %v", raw, got, err)
		}
	}
	if _, err := coreSlotNumber("two"); err == nil {
		t.Fatal("a slot that is no number is refused")
	}
}

func TestTheCoreDoorsSayWhatWasBooked(t *testing.T) {
	tests := []struct{ name, got, want string }{
		{"package visit", coreVisitBooked(2, "Training Follow Up"), "Core Visit V2 (Training Follow Up) scheduled successfully."},
		{"request", coreVisitPending(2, "Training Follow Up", "Paul N."),
			"Core Visit V2 (Training Follow Up) scheduled, pending Paul N.'s approval. It takes effect on your plan and enters your budget once approved."},
		{"outreach", coreOutreachBooked("Donor Visit"), "Donor Visit scheduled. It is not one of the package's four visits."},
		{"outreach request", coreOutreachPending("Donor Visit", "Paul N."),
			"Donor Visit scheduled, pending Paul N.'s approval. It takes effect on your plan and enters your budget once approved."},
		{"training", coreTrainingBooked(1, "EdTech"), "Core Training T1 (EdTech) and its school visit scheduled successfully."},
		{"universal", coreUniversalBooked("SSA Training"), "SSA Training and its school visit scheduled. It is on top of the package's four trainings."},
		{"colleague", onColleaguesCorePlan("Booked.", "Paul N."),
			"Booked. It is on Paul N.'s My Plan, because they are the responsible staff member — you will find it on the Calendar."},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.got != tt.want {
				t.Fatalf("got %q", tt.got)
			}
		})
	}
}
