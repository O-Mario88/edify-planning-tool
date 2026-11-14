package btpages

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
)

func TestOnlyProfileReadersGetSchoolLinksAndTheOfficerPrepares(t *testing.T) {
	r := btportfolio.Rules
	if r.NavRole != "BusinessTransformationOfficer" {
		t.Errorf("the preparer is the BT officer, got %q", r.NavRole)
	}
	if len(r.PositiveImpact) != 2 || len(r.SchoolLinkRoles) == 0 {
		t.Errorf("positive impact %v, school link roles %v", r.PositiveImpact, r.SchoolLinkRoles)
	}
	for _, role := range r.SchoolLinkRoles {
		if role == "RegionalVicePresident" {
			t.Error("the RVP reads school names as text")
		}
	}
}
