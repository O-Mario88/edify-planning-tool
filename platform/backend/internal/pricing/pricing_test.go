package pricing

import (
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

func strp(s string) *string { return &s }

func TestFieldStaffAreReadAgainstTheirPrimaryDistrictAndHeadOfficeAgainstTheZone(t *testing.T) {
	cceo := traveller{known: true, hasProfile: true, roles: []string{"CCEO"}, primaryDistrict: strp("d-home")}
	if got := cceo.decide("d-home", "Gulu", "secondary"); got != "primary" {
		t.Errorf("a CCEO at home: %q", got)
	}
	if got := cceo.decide("d-away", "Kampala", "primary"); got != "secondary" {
		t.Errorf("a CCEO away (even in Kampala): %q", got)
	}
	unset := traveller{known: true, hasProfile: true, roles: []string{"Program Lead"}}
	if got := unset.decide("d", "Gulu", "secondary"); got != "secondary" {
		t.Errorf("a lead with no primary district reads the district's own type: %q", got)
	}
	cd := traveller{known: true, hasProfile: true, roles: []string{"CountryDirector"}, primaryDistrict: strp("d")}
	if cd.decide("d", " wakiso ", "secondary") != "primary" || cd.decide("d", "Gulu", "primary") != "secondary" {
		t.Error("head office is read against the Kampala, Wakiso and Mukono zone")
	}
	admin := traveller{known: true, roles: []string{"CCEO"}}
	if admin.decide("d", "Gulu", "primary") != "secondary" {
		t.Error("a field role with no profile is head office")
	}
	if (traveller{}).decide("d", "Gulu", "primary") != "primary" {
		t.Error("nobody to resolve for reads the district's own type")
	}
	if !holdsFieldRole(nil, "pl") || holdsFieldRole([]string{"Admin"}, "CCEO") {
		t.Error("field roles are the roles held, else the active one")
	}
}

func TestTheSecondNightRateIsForAnyRoleHeldOnTheList(t *testing.T) {
	if accommodationKeyFor([]string{"CCEO"}, "Program Lead", true) != rules.AccommodationKey {
		t.Error("an officer acting as a lead keeps the CCEO rate")
	}
	if accommodationKeyFor([]string{"CCEO", "Program Lead"}, "CCEO", true) != rules.ManagementAccommodationKey {
		t.Error("a Program Lead in their CCEO hat")
	}
	if accommodationKeyFor(nil, "CountryDirector", true) != rules.ManagementAccommodationKey {
		t.Error("an account listing no roles reads its active role")
	}
	if accommodationKeyFor(nil, "", false) != rules.AccommodationKey {
		t.Error("nobody to resolve for is the CCEO rate")
	}
}

func TestAnUnknownProfileIsRefusedAndNoCardPricesNothing(t *testing.T) {
	if _, err := Profiled(Input{Profile: "NO_SUCH"}); !errors.Is(err, ErrUnknownProfile) {
		t.Fatalf("an unknown profile: %v", err)
	}
	a, err := Profiled(Input{Activity: costing.Activity{ActivityType: "x"}, Profile: "ONETEST"})
	if err != nil || a.ActivityType != "school_visit" || a.CostingKind != "onetest" {
		t.Fatalf("OneTest: %+v %v", a, err)
	}
	d := dual(costing.Activity{ActivityType: "school_visit"}, "", nil, nil)
	if d.Viability != "configuration_missing" || d.CanSchedule || d.HasReference ||
		len(d.MissingReference) != 1 || d.MissingReference[0] != "rate_card" ||
		len(d.Warnings) != 1 {
		t.Fatalf("no cards: %+v", d)
	}
}
