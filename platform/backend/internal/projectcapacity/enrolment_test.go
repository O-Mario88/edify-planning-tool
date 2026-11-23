package projectcapacity

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestAProjectOptionNamesItsCodeAndCoordinator(t *testing.T) {
	cases := []struct{ name, code, coordinator, want string }{
		{"CCSEL", "SP-CCSEL", "Allan", "CCSEL (SP-CCSEL) · Allan"},
		{"CCSEL", "", "Allan", "CCSEL (No Code) · Allan"},
		{"CCSEL", "SP-CCSEL", "", "CCSEL (SP-CCSEL)"},
	}
	for _, tc := range cases {
		if got := enrolmentLabel(tc.name, tc.code, tc.coordinator); got != tc.want {
			t.Errorf("got %q, want %q", got, tc.want)
		}
	}
}

func TestAFullAllocationBlocksTheProject(t *testing.T) {
	const full = "You have reached your allocation of 3 schools for CCSEL. No additional schools can be added unless the Project Coordinator increases your allocation."
	const none = "You have no school allocation for CCSEL. Ask its Project Coordinator to set one."
	cases := []struct {
		name              string
		held              *heldPlaces
		managed, teamHeld bool
		want              string
	}{
		{name: "places left", held: &heldPlaces{maximum: 3, assigned: 2}, managed: true},
		{name: "none left", held: &heldPlaces{maximum: 3, assigned: 3}, managed: true, want: full},
		{name: "over its allocation", held: &heldPlaces{maximum: 3, assigned: 5}, managed: true, want: full},
		{name: "managed, none of mine", managed: true, want: none},
		{name: "my team holds places", managed: true, teamHeld: true},
		{name: "no allocations on the project"},
	}
	for _, tc := range cases {
		if got := capacityBlock("CCSEL", tc.held, tc.managed, tc.teamHeld); got != tc.want {
			t.Errorf("%s: got %q", tc.name, got)
		}
	}
}

func TestOnlyStaffOutsideTheExemptRolesUsePlaces(t *testing.T) {
	principal := func(role string) auth.Principal {
		return auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: role, StaffProfileID: "s1"}}
	}
	for _, role := range []string{"ProjectCoordinator", "ImpactAssessment", "CountryDirector", "Admin"} {
		if got := consumingStaffID(principal(role)); got != "" {
			t.Errorf("%s uses places: %q", role, got)
		}
	}
	for _, role := range []string{"CCEO", "Program Lead"} {
		if got := consumingStaffID(principal(role)); got != "s1" {
			t.Errorf("%s: %q", role, got)
		}
	}
}

func TestSchoolFocusExcludesTheOtherCohort(t *testing.T) {
	if got := excludedFocus("core"); got != "client" {
		t.Errorf("a Core school: %q", got)
	}
	for _, schoolType := range []string{"client", "champion", "core_trained", ""} {
		if got := excludedFocus(schoolType); got != "core" {
			t.Errorf("%q: %q", schoolType, got)
		}
	}
}
