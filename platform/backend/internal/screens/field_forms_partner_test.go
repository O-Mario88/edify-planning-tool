package screens

import (
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnercapabilities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

func partnerField(t *testing.T, drawer *screensv1.PageDrawer, name string) *screensv1.DrawerField {
	t.Helper()
	for _, item := range drawer.GetItems() {
		if item.GetField().GetName() == name {
			return item.GetField()
		}
	}
	t.Fatalf("no %s field", name)
	return nil
}

func TestOnlyAdminCountryDirectorAndIAAddPartners(t *testing.T) {
	form, ok := fieldFormFor("/partners/create")
	if !ok {
		t.Fatal("the partner form is not served")
	}
	for _, role := range []string{rbac.Admin, roleCD, roleIA} {
		if why := form.refusal(fieldPrincipal(role)); why != "" {
			t.Errorf("%s refused: %s", role, why)
		}
	}
	const words = "Only an Admin, Country Director or Impact Assessment can add partner organisations."
	for _, role := range []string{rbac.CCEO, rbac.ProgramLead, rolePC, roleAccountant, "PartnerAdmin"} {
		if why := form.refusal(fieldPrincipal(role)); why != words {
			t.Errorf("%s: %q", role, why)
		}
	}
	if why := form.refusal(fieldPrincipal("ClusterLeader")); why != "Access Denied: Your active role does not have permission to view Partners." {
		t.Errorf("Cluster Leader: %q", why)
	}
	if !form.withheldFromTeamMembers {
		t.Error("a partner's team member does not hold the Partners page")
	}
}

func TestThePartnerFormAsksForTheOrganisationOnly(t *testing.T) {
	drawer := partnerCreateDrawer([]string{"Central", "Eastern"}, []partnercapabilities.Group{
		{Key: "leadership", Label: "Leadership", Activities: []partnercapabilities.Activity{{Code: "L1", Name: "Coaching"}}},
		{Key: "loan", Label: "Loan"},
	}, true)
	if drawer.GetTitle() != "Add partner organisation" || drawer.GetSubmitLabel() != "Add organisation" || !drawer.GetCanSubmit() {
		t.Fatalf("head: %v", drawer)
	}
	name := partnerField(t, drawer, "name")
	if !name.GetRequired() || name.GetMaxLength() != 255 {
		t.Fatalf("name: %v", name)
	}
	role := partnerField(t, drawer, "partner_role")
	if role.GetValue() != "delivery" || len(role.GetOptions()) != 2 || role.GetOptions()[1].GetLabel() != "Loan Partner" {
		t.Fatalf("role: %v", role)
	}
	if regions := partnerField(t, drawer, "region_names"); regions.GetKind() != "checklist" || len(regions.GetOptions()) != 2 {
		t.Fatalf("regions: %v", regions)
	}
	last := drawer.GetItems()[len(drawer.GetItems())-1].GetNote().GetText()
	if last != "No sign-in account is created here. Set up the organisation's login from the Partner Organisations directory once it is saved." {
		t.Fatalf("login note: %q", last)
	}
}

func TestEveryTickBoxOnThePartnerFormSaysWhatItIs(t *testing.T) {
	drawer := partnerCreateDrawer(nil, []partnercapabilities.Group{
		{Key: "leadership", Label: "Leadership", Activities: []partnercapabilities.Activity{{Code: "L1", Name: "Coaching"}, {Code: "S1", Name: "Support"}}},
		{Key: "enrolment", Label: "Enrolment", Activities: []partnercapabilities.Activity{{Code: "L1", Name: "Coaching"}}},
		{Key: "loan", Label: "Loan"},
	}, false)
	groups := partnerField(t, drawer, "ssa_interventions").GetOptions()
	if len(groups) != 3 || groups[0].GetLabel() != "Leadership" || groups[0].GetDetail() != "2 activities" || groups[1].GetDetail() != "1 activity" || groups[2].GetDetail() != "" {
		t.Fatalf("interventions: %v", groups)
	}
	activities := partnerField(t, drawer, "activity_codes").GetOptions()
	if len(activities) != 2 {
		t.Fatalf("an activity under two interventions is one tick box: %v", activities)
	}
	if activities[0].GetValue() != "L1" || activities[0].GetLabel() != "Coaching" || activities[0].GetDetail() != "Leadership · Enrolment" {
		t.Fatalf("activity: %v", activities[0])
	}
}

func TestThePartnerFormSaysWhenNoRegionsExist(t *testing.T) {
	drawer := partnerCreateDrawer(nil, nil, false)
	for _, item := range drawer.GetItems() {
		if item.GetField().GetName() == "region_names" {
			t.Fatal("an empty region list is drawn")
		}
	}
	found := false
	for _, item := range drawer.GetItems() {
		if item.GetNote().GetText() == "No regions are set up yet. Add the organisation now and record its regions once they are." {
			found = true
		}
	}
	if !found {
		t.Fatal("no notice about regions")
	}
	last := drawer.GetItems()[len(drawer.GetItems())-1].GetNote().GetText()
	if last != "No sign-in account is created here. A user administrator is told the organisation is waiting and sets up its logins." {
		t.Fatalf("login note: %q", last)
	}
}
