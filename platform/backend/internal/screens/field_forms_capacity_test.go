package screens

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

func TestCapacityFormsAnswerTheirPages(t *testing.T) {
	set, ok := fieldFormFor("/projects/capacity/set")
	if !ok {
		t.Fatal("the capacity form is not served")
	}
	for _, role := range []string{rbac.Admin, rolePC, roleIA} {
		if why := set.refusal(fieldPrincipal(role)); why != "" {
			t.Errorf("%s refused: %s", role, why)
		}
	}
	if why := set.refusal(fieldPrincipal(rbac.CCEO)); why != "Access Denied: Your active role does not have permission to view Project Capacity." {
		t.Errorf("CCEO: %q", why)
	}
	withdraw, ok := fieldFormFor("/projects/capacity/withdraw")
	if !ok {
		t.Fatal("the withdraw form is not served")
	}
	if why := withdraw.refusal(fieldPrincipal(rbac.CCEO)); why != "" {
		t.Errorf("a CCEO holds the monitoring page: %q", why)
	}
	if why := withdraw.refusal(fieldPrincipal(roleAccountant)); why != "Access Denied: Your active role does not have permission to view Project Monitoring." {
		t.Errorf("Accountant: %q", why)
	}
}

func TestTheCapacityFormAsksForTheProjectFirst(t *testing.T) {
	drawer := capacitySetDrawer(projectcapacity.SetForm{Projects: []projectcapacity.Choice{{Value: "p1", Label: "CCSEL (SP-CCSEL)"}}})
	staff := drawer.GetItems()[1].GetField()
	if !staff.GetReadOnly() || staff.GetOptions()[0].GetLabel() != "Choose the project first" {
		t.Fatalf("staff before a project: %v", staff)
	}
	if got := drawer.GetItems()[0].GetField().GetOptions()[1].GetLabel(); got != "CCSEL (SP-CCSEL)" {
		t.Fatalf("project option: %q", got)
	}
	maximum := drawer.GetItems()[2].GetField()
	if maximum.GetKind() != "number" || maximum.GetMin() != 1 || maximum.GetStep() != 1 || !maximum.GetRequired() {
		t.Fatalf("maximum: %v", maximum)
	}
	if drawer.GetSubmitLabel() != "Save Capacity" {
		t.Fatalf("submit: %q", drawer.GetSubmitLabel())
	}
}

func TestSomeoneAlreadyAllocatedIsShownButNotChosen(t *testing.T) {
	drawer := capacitySetDrawer(projectcapacity.SetForm{
		Project: "p1", Projects: []projectcapacity.Choice{{Value: "p1", Label: "CCSEL"}},
		Staff: []projectcapacity.Choice{{Value: "s1", Label: "Ada"}, {Value: "s2", Label: "Ben", Taken: true}},
	})
	options := drawer.GetItems()[1].GetField().GetOptions()
	if options[0].GetLabel() != "Choose a staff member" || options[1].GetDisabled() {
		t.Fatalf("options: %v", options)
	}
	if !options[2].GetDisabled() || options[2].GetLabel() != "Ben — already allocated, edit from the table" {
		t.Fatalf("taken: %v", options[2])
	}
	empty := capacitySetDrawer(projectcapacity.SetForm{Project: "p1"})
	if got := empty.GetItems()[1].GetField().GetHelp(); got != "No active CCEO or Programme Lead works in this project's country." {
		t.Fatalf("no one eligible: %q", got)
	}
}

func TestWithdrawDrawerAsksForAReasonOrSaysWhyNot(t *testing.T) {
	open := withdrawSchoolDrawer(projectcapacity.WithdrawForm{School: "Goma", Project: "CCSEL", Assigned: "9 Nov 2026 · Ada", Holder: "Ada"})
	if open.GetSubmitLabel() != "Withdraw School" || !open.GetCanSubmit() {
		t.Fatalf("open: %v", open)
	}
	if got := open.GetItems()[1].GetNote().GetText(); got != "This school has not entered project execution and can be withdrawn. Its place returns to Ada's allocation." {
		t.Fatalf("note: %q", got)
	}
	other := open.GetItems()[3].GetField()
	if other.GetName() != "reason_other" || other.GetMaxLength() != 500 || other.GetShowWhen()[0].GetValues()[0] != "other" {
		t.Fatalf("other: %v", other)
	}
	blocked := withdrawSchoolDrawer(projectcapacity.WithdrawForm{School: "Goma", Project: "CCSEL", Assigned: "9 Nov 2026",
		Block: &projectcapacity.Block{Title: "Cannot withdraw", Message: "This school already has a planned project activity."}})
	if blocked.GetCanSubmit() || blocked.GetCancelLabel() != "Close" || len(blocked.GetItems()) != 2 {
		t.Fatalf("blocked: %v", blocked)
	}
	if note := blocked.GetItems()[1].GetNote(); note.GetTone() != "warning" || note.GetText() != "Cannot withdraw This school already has a planned project activity." {
		t.Fatalf("block note: %v", note)
	}
}
