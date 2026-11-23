package screens

import (
	"strings"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func fieldPrincipal(role string) auth.Principal {
	return auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: role}}
}

func TestFieldFormRefusals(t *testing.T) {
	const noPlaybook = "Access Denied: Your active role does not have permission to view Core Schools."
	const noHistory = "Access Denied: Your active role does not have permission to view My Professional Development."
	tests := []struct {
		role, path, want string
	}{
		{"CCEO", "/core-schools/strategy-playbook", ""},
		{"Program Lead", "/core-schools/strategy-playbook", ""},
		{"Accountant", "/core-schools/strategy-playbook", ""},
		{"Admin", "/core-schools/strategy-playbook/", ""},
		{"HumanResources", "/core-schools/strategy-playbook", noPlaybook},
		{"RegionalVicePresident", "/core-schools/strategy-playbook", noPlaybook},
		{"PartnerAdmin", "/core-schools/strategy-playbook", noPlaybook},
		{"HumanResources", "/my-professional-development/allocation-history", ""},
		{"RegionalVicePresident", "/my-professional-development/allocation-history", ""},
		{"ProjectCoordinator", "/my-professional-development/allocation-history", ""},
		{"RegionalProgramLead", "/my-professional-development/allocation-history", noHistory},
		{"PartnerFieldOfficer", "/my-professional-development/allocation-history", noHistory},
		{"MfiLoanOfficer", "/my-professional-development/allocation-history", noHistory},
	}
	for _, tc := range tests {
		t.Run(tc.role+" "+tc.path, func(t *testing.T) {
			form, ok := fieldFormFor(tc.path)
			if !ok {
				t.Fatal("not a field form")
			}
			if got := form.refusal(fieldPrincipal(tc.role)); got != tc.want {
				t.Fatalf("refusal = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestFieldFormsRefuseAnActingLeaderRatherThanGuess(t *testing.T) {
	acting := fieldPrincipal("CountryDirector")
	acting.InActingAppointment = true
	form, _ := fieldFormFor("/core-schools/strategy-playbook")
	if form.refusal(acting) == "" {
		t.Fatal("an acting leader's withheld pages are not decided here, so the form must refuse")
	}
}

func TestOtherPathsAreNotFieldForms(t *testing.T) {
	for _, path := range []string{"/core-schools", "/core-schools/strategy-playbook/extra", "/my-professional-development"} {
		if _, ok := fieldFormFor(path); ok {
			t.Fatalf("%s is not a field form", path)
		}
	}
}

func TestStrategyPlaybookReadsAsTheExistingForm(t *testing.T) {
	drawer := strategyPlaybookDrawer()
	if drawer.GetTitle() != "Core strategy playbook" || !drawer.GetHasRequired() || drawer.GetCancelLabel() != "Cancel" {
		t.Fatalf("drawer = %q required=%v cancel=%q", drawer.GetTitle(), drawer.GetHasRequired(), drawer.GetCancelLabel())
	}
	if drawer.GetCanSubmit() || drawer.GetSubmitLabel() != "" {
		t.Fatal("the playbook only informs")
	}
	items := drawer.GetItems()
	if len(items) != 7 || items[0].GetHeading() != "The Core program rule" || items[2].GetHeading() != "Operational phase guide" {
		t.Fatalf("items = %v", items)
	}
	if !strings.HasPrefix(items[3].GetText(), "Phase 1: SSA assessment and V1 Complete the SSA") {
		t.Fatalf("phase 1 = %q", items[3].GetText())
	}
	if !strings.HasSuffix(items[6].GetText(), "Advance qualifying core schools to Champion status.") {
		t.Fatalf("phase 4 = %q", items[6].GetText())
	}
}
