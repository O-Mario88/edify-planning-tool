package activities

import (
	"net/url"
	"testing"
)

func TestTheCoreAssignFormIsRead(t *testing.T) {
	req, taken := CoreAssignRequestFromForm("1045", url.Values{
		"partner_id": {" p1 "}, "purpose_of_visit": {" training_follow_up "}, "notes": {" a note "},
		"source_activity_id": {" a1 "}, "training_course_id": {" c1 "}, "focus_intervention": {" leadership "},
		"visit_training_number": {" 3 "},
	})
	want := CoreAssignRequest{SchoolCode: "1045", PartnerID: "p1", Purpose: "training_follow_up", Notes: "a note",
		SourceActivityID: "a1", CourseID: "c1", Focus: "leadership", SlotNumber: "3"}
	if !taken || req != want {
		t.Fatalf("taken %v, got %+v", taken, req)
	}
}

func TestACoreAssignWithAnUnknownFieldIsNotTaken(t *testing.T) {
	if _, taken := CoreAssignRequestFromForm("1045", url.Values{"project_id": {"x"}}); taken {
		t.Fatal("a project's hand-over is handed on")
	}
}

func TestThePartnerHalfSaysWhoseWorkIsNext(t *testing.T) {
	tests := []struct {
		kind string
		used int
		want string
	}{
		{coreSlotVisit, 2, "Mpatta already has its 2 partner core visits (2/2). A Core package is 2 staff and 2 partner visits, so the next visit here is the staff's."},
		{coreSlotTraining, 3, "Mpatta already has its 2 partner core trainings (3/2). A Core package is 2 staff and 2 partner trainings, so the next training here is the staff's."},
	}
	for _, tt := range tests {
		if got := corePartnerSideRefusal("Mpatta", tt.kind, tt.used); got != tt.want {
			t.Fatalf("got %q", got)
		}
	}
}

func TestAPartnerDeliversWhatItRecords(t *testing.T) {
	tests := []struct {
		name  string
		codes []string
		want  bool
	}{
		{"no activities recorded", nil, true},
		{"records this one", []string{"ED", "TECH"}, true},
		{"records others", []string{"TECH"}, false},
	}
	for _, tt := range tests {
		if got := partnerDelivers(tt.codes, "ED"); got != tt.want {
			t.Fatalf("%s = %v", tt.name, got)
		}
	}
}

func TestAHandOverGivesItsReason(t *testing.T) {
	if got, want := trainingHandOverReason([]string{"Build", "Aim"}, "Digital"), "Priority activity: Aim, Build"; got != want {
		t.Fatalf("got %q", got)
	}
	if got, want := trainingHandOverReason(nil, "Digital"), "Governed Digital training."; got != want {
		t.Fatalf("got %q", got)
	}
	if got, want := visitHandOverReason("SSA Support"), "SSA Support selected by the assigning staff member."; got != want {
		t.Fatalf("got %q", got)
	}
}

func TestThePartnerIsToldWhatItWasGiven(t *testing.T) {
	if got, want := coreAssignedBody("Mpatta", "Training Follow Up"), "Your organization has been assigned to support Mpatta with Training Follow Up. Choose the date to deliver it."; got != want {
		t.Fatalf("got %q", got)
	}
	if got, want := coreAssignedMessage("Build Africa"), "Core support assigned to Build Africa successfully."; got != want {
		t.Fatalf("got %q", got)
	}
}

// NotificationLinkResolver's partner_scheduled_activity: the link follows the
// role of the person told, and a role it does not name opens the dashboard.
func TestThePartnerQueueNoticeLinksByRole(t *testing.T) {
	tests := []struct{ role, route, label string }{
		{"PartnerFieldOfficer", "/my-plan", "Partner My Plan"},
		{"CCEO", "/my-plan", "Staff My Plan"},
		{"Program Lead", "/partner-oversight/", "Open Partner Oversight"},
		{"ProjectLeader", "/partner-oversight/", "Open Partner Oversight"},
		{"ProjectCoordinator", "/my-plan", "Open My Plan"},
		{"PartnerAdmin", "/dashboard", "View Dashboard"},
		{"", "/dashboard", "View Dashboard"},
	}
	for _, tt := range tests {
		t.Run(tt.role, func(t *testing.T) {
			route, label := partnerQueueLink(tt.role)
			if route != tt.route || label != tt.label {
				t.Fatalf("got %s, %s", route, label)
			}
		})
	}
}
