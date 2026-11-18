package countryconfig

import (
	"strings"
	"testing"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

const someMembership = "0b6f2c4e-5d1a-4f3e-9a7b-2c8d1e6f4a90"

// The regional roles work across every country (owner, 2026-11-18).
var regional = []string{"RegionalVicePresident", "HumanResources", "RegionalProgramLead", "BusinessTransformationOfficer"}

func TestCountryRoleChecks(t *testing.T) {
	officer := func() *countriesv1.AssignCountryRoleRequest {
		return &countriesv1.AssignCountryRoleRequest{MembershipId: someMembership, Role: "CCEO", Reason: "Kenya pilot officer"}
	}
	if a, err := roleOf(officer()); err != nil || a.scopeType != country.ScopePortfolio || len(a.regionIDs) != 0 {
		t.Fatalf("an officer: %+v, %v", a, err)
	}
	if a, err := roleOf(&countriesv1.AssignCountryRoleRequest{MembershipId: someMembership, Role: "CountryDirector", Reason: "Lead"}); err != nil || a.scopeType != country.ScopeCountry {
		t.Errorf("a Country Director: %+v, %v", a, err)
	}
	for _, role := range regional {
		_, err := roleOf(&countriesv1.AssignCountryRoleRequest{MembershipId: someMembership, Role: role, RegionIds: []string{"r1"}, Reason: "Regional"})
		if err == nil || !strings.Contains(err.Error(), "works across every country") {
			t.Errorf("%s assigned in one country: %v", role, err)
		}
	}

	for name, change := range map[string]func(*countriesv1.AssignCountryRoleRequest){
		"no membership":           func(r *countriesv1.AssignCountryRoleRequest) { r.MembershipId = "" },
		"a membership not an id":  func(r *countriesv1.AssignCountryRoleRequest) { r.MembershipId = "m1" },
		"an unknown role":         func(r *countriesv1.AssignCountryRoleRequest) { r.Role = "Officer" },
		"Admin":                   func(r *countriesv1.AssignCountryRoleRequest) { r.Role = "Admin" },
		"regions for an officer":  func(r *countriesv1.AssignCountryRoleRequest) { r.RegionIds = []string{"r1"} },
		"a blank region":          func(r *countriesv1.AssignCountryRoleRequest) { r.RegionIds = []string{" "} },
		"a region id too long":    func(r *countriesv1.AssignCountryRoleRequest) { r.RegionIds = []string{strings.Repeat("r", 31)} },
		"no reason":               func(r *countriesv1.AssignCountryRoleRequest) { r.Reason = "  " },
		"a reason over the limit": func(r *countriesv1.AssignCountryRoleRequest) { r.Reason = strings.Repeat("x", maxReason+1) },
	} {
		r := officer()
		change(r)
		if _, err := roleOf(r); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestAssignableRolesLeaveOutAdminAndTheRegionalRoles(t *testing.T) {
	seen, labels := map[string]string{}, map[string]string{}
	for _, r := range assignableRoles() {
		seen[r.GetRole()], labels[r.GetRole()] = r.GetScopeType(), r.GetLabel()
	}
	if labels["CountryDirector"] != "Country Director" || labels["ImpactAssessment"] != "Impact Assessment" {
		t.Errorf("role labels %v", labels)
	}
	for _, role := range append([]string{"Admin"}, regional...) {
		if _, ok := seen[role]; ok {
			t.Errorf("%s is offered as a country role", role)
		}
	}
	for role, want := range map[string]string{"CCEO": country.ScopePortfolio, "CountryDirector": country.ScopeCountry,
		"ImpactAssessment": country.ScopeCountry} {
		if seen[role] != want {
			t.Errorf("%s is offered with scope %q, want %q", role, seen[role], want)
		}
	}
}
