package oversightportfolio

import (
	"reflect"
	"testing"
)

// The existing page's COVERAGE_LENS_ROLES names "RegionalVP" where the role is
// "RegionalVicePresident", so the RVP never gets the Portfolio and Coverage
// lenses its comment says the role reads. Go draws the doors the export
// computes with the name corrected; every other role keeps the existing
// page's (owner, 2026-11-13: "Can you fix those from the go side";
// intended.json go-fix-rvp-lens).
func TestTheRegionalVicePresidentGetsTheLensesTheListMeant(t *testing.T) {
	rvp := doorsFor("RegionalVicePresident")
	if !rvp.Portfolio || len(rvp.LensTabsCountry) == 0 {
		t.Fatalf("the RVP's doors: %+v", rvp)
	}
	if rules.Doors["RegionalVicePresident"].Portfolio {
		t.Fatal("the existing page's doors were expected to lack the lens (the defect this fixes)")
	}
	for role, existing := range rules.Doors {
		if role == "RegionalVicePresident" {
			continue
		}
		if got := doorsFor(role); !reflect.DeepEqual(got, existing) {
			t.Fatalf("%s's doors changed: %+v", role, got)
		}
	}
	if len(rules.FixedDoors) != 1 {
		t.Fatalf("only the RVP's doors are corrected: %v", rules.FixedDoors)
	}
}
