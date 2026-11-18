package countryconfig

import (
	"strings"
	"testing"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

const someMembership = "0b6f2c4e-5d1a-4f3e-9a7b-2c8d1e6f4a90"

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
	a, err := roleOf(&countriesv1.AssignCountryRoleRequest{MembershipId: someMembership, Role: "RegionalProgramLead",
		RegionIds: []string{" r1 ", "r2", "r1"}, Reason: "Nairobi and Coast"})
	if err != nil || a.scopeType != country.ScopeRegions || strings.Join(a.regionIDs, ",") != "r1,r2" {
		t.Errorf("a regional lead: %+v, %v", a, err)
	}

	for name, change := range map[string]func(*countriesv1.AssignCountryRoleRequest){
		"no membership":          func(r *countriesv1.AssignCountryRoleRequest) { r.MembershipId = "" },
		"a membership not an id": func(r *countriesv1.AssignCountryRoleRequest) { r.MembershipId = "m1" },
		"an unknown role":        func(r *countriesv1.AssignCountryRoleRequest) { r.Role = "Officer" },
		"Admin":                  func(r *countriesv1.AssignCountryRoleRequest) { r.Role = "Admin" },
		"regions for an officer": func(r *countriesv1.AssignCountryRoleRequest) { r.RegionIds = []string{"r1"} },
		"a regional role, bare":  func(r *countriesv1.AssignCountryRoleRequest) { r.Role = "RegionalVicePresident" },
		"a blank region": func(r *countriesv1.AssignCountryRoleRequest) {
			r.Role, r.RegionIds = "RegionalProgramLead", []string{"r1", " "}
		},
		"a region id too long": func(r *countriesv1.AssignCountryRoleRequest) {
			r.Role, r.RegionIds = "RegionalProgramLead", []string{strings.Repeat("r", 31)}
		},
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

func TestAssignableRolesLeaveOutAdmin(t *testing.T) {
	seen, labels := map[string]string{}, map[string]string{}
	for _, r := range assignableRoles() {
		seen[r.GetRole()], labels[r.GetRole()] = r.GetScopeType(), r.GetLabel()
	}
	if labels["CountryDirector"] != "Country Director" || labels["RegionalProgramLead"] != "Regional Programme Lead" {
		t.Errorf("role labels %v", labels)
	}
	if _, ok := seen["Admin"]; ok {
		t.Error("Admin is offered as a country role")
	}
	for role, want := range map[string]string{"CCEO": country.ScopePortfolio, "CountryDirector": country.ScopeCountry,
		"RegionalVicePresident": country.ScopeRegions, "RegionalProgramLead": country.ScopeRegions} {
		if seen[role] != want {
			t.Errorf("%s is offered with scope %q, want %q", role, seen[role], want)
		}
	}
}
