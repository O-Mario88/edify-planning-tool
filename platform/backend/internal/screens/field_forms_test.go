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

func TestPartnerMemberFormAddress(t *testing.T) {
	form, ok := fieldFormFor("/partners/partner-1/members/drawer")
	if !ok || form.recordID("/partners/partner-1/members/drawer/") != "partner-1" {
		t.Fatalf("ok=%v id=%q", ok, form.recordID("/partners/partner-1/members/drawer/"))
	}
	for _, path := range []string{"/partners//members/drawer", "/partners/a/b/members/drawer", "/partners/partner-1/members"} {
		if _, ok := fieldFormFor(path); ok {
			t.Fatalf("%s is not the member form", path)
		}
	}
	if !form.withheldFromTeamMembers {
		t.Fatal("a partner's team member does not hold the partner page")
	}
}

func TestPartnerMemberFormRefusals(t *testing.T) {
	form, _ := fieldFormFor("/partners/partner-1/members/drawer")
	for _, role := range []string{"CCEO", "HumanResources", "PartnerFieldOfficer", "MfiLoanOfficer", "BusinessTransformationOfficer"} {
		if got := form.refusal(fieldPrincipal(role)); got != "" {
			t.Fatalf("%s: %q", role, got)
		}
	}
	const want = "Access Denied: Your active role does not have permission to view Partner Detail."
	if got := form.refusal(fieldPrincipal("ClusterLeader")); got != want {
		t.Fatalf("ClusterLeader: %q", got)
	}
}

func TestPartnerMemberFormFields(t *testing.T) {
	drawer := partnerMemberDrawer("Literacy Uganda", "Grace N")
	if drawer.GetTitle() != "Add to the Literacy Uganda roster" || drawer.GetSubmitLabel() != "Add to roster" || !drawer.GetCanSubmit() {
		t.Fatalf("drawer = %q / %q", drawer.GetTitle(), drawer.GetSubmitLabel())
	}
	names := fieldNames(drawer)
	if strings.Join(names, ",") != "name,role,title,phone,email" {
		t.Fatalf("fields = %v", names)
	}
	name := drawer.GetItems()[0].GetField()
	if name.GetValue() != "Grace N" || !name.GetRequired() || name.GetPlaceholder() != "e.g. Grace Nakato" {
		t.Fatalf("name = %+v", name)
	}
	role := drawer.GetItems()[1].GetField()
	if role.GetKind() != "select" || role.GetValue() != "staff" || len(role.GetOptions()) != 2 || role.GetOptions()[1].GetLabel() != "Volunteer" {
		t.Fatalf("role = %+v", role)
	}
	if email := drawer.GetItems()[4].GetField(); email.GetKind() != "email" || email.GetPlaceholder() != "name@partner.org" {
		t.Fatalf("email = %+v", email)
	}
}

func TestProjectCreateFormRefusals(t *testing.T) {
	const onlyConfigurers = "Only a Special Project Coordinator, Impact Assessment, the Country Director, or Admin may create Projects."
	const noPage = "Access Denied: Your active role does not have permission to view Projects."
	tests := []struct{ role, want string }{
		{"CountryDirector", ""},
		{"ImpactAssessment", ""},
		{"ProjectCoordinator", ""},
		{"Admin", ""},
		{"CCEO", onlyConfigurers},
		{"Program Lead", onlyConfigurers},
		{"Accountant", noPage},
		{"PartnerAdmin", noPage},
		{"ClusterLeader", noPage},
	}
	form, ok := fieldFormFor("/projects/create/")
	if !ok {
		t.Fatal("not a field form")
	}
	for _, tc := range tests {
		t.Run(tc.role, func(t *testing.T) {
			if got := form.refusal(fieldPrincipal(tc.role)); got != tc.want {
				t.Fatalf("refusal = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestProjectCreateFormFields(t *testing.T) {
	drawer := projectCreateDrawer(
		[]projectCatalogueChoice{{id: "c1", name: "Biblical Integration", code: "BIBLICAL_INTEGRATION", delivery: "cluster_training"}},
		[]fieldChoice{{id: "p1", name: "Build Africa"}},
	)
	if drawer.GetTitle() != "Create special project" || drawer.GetSubmitLabel() != "Create proposed project" || !drawer.GetCanSubmit() {
		t.Fatalf("drawer = %q / %q", drawer.GetTitle(), drawer.GetSubmitLabel())
	}
	want := "name,code,category,schoolFocus,budgetCeilingUgx,measurementStartFy,measurementEndFy,targetInterventions,catalogueItemIds,partnerIds"
	if got := strings.Join(fieldNames(drawer), ","); got != want {
		t.Fatalf("fields = %s", got)
	}
	items := drawer.GetItems()
	if f := items[0].GetField(); !f.GetRequired() || f.GetMaxLength() != 255 {
		t.Fatalf("name = %+v", f)
	}
	if f := items[2].GetField(); len(f.GetOptions()) != 4 || f.GetOptions()[0].GetLabel() != "Choose…" {
		t.Fatalf("category = %+v", f)
	}
	if f := items[3].GetField(); f.GetValue() != "all" || f.GetOptions()[0].GetLabel() != "Client and Core Schools" {
		t.Fatalf("focus = %+v", f)
	}
	if f := items[4].GetField(); f.Min == nil || f.GetMin() != 0 || f.GetStep() != 1 {
		t.Fatalf("budget = %+v", f)
	}
	if f := items[7].GetField(); len(f.GetOptions()) != 9 || f.GetOptions()[8].GetValue() != "general" {
		t.Fatalf("interventions = %+v", f)
	}
	if o := items[8].GetField().GetOptions()[0]; o.GetDetail() != "BIBLICAL_INTEGRATION · Cluster Training" {
		t.Fatalf("catalogue = %+v", o)
	}
	if o := items[9].GetField().GetOptions()[0]; o.GetValue() != "p1" || o.GetLabel() != "Build Africa" {
		t.Fatalf("partner = %+v", o)
	}
}

func TestPartnerChoicesSortIgnoringCase(t *testing.T) {
	got := sortedFieldChoices([]fieldChoice{{id: "1", name: "World Reader"}, {id: "2", name: "alpha"}, {id: "3", name: "Build Africa"}})
	if got[0].id != "2" || got[1].id != "3" || got[2].id != "1" {
		t.Fatalf("order = %+v", got)
	}
}

func TestWorkPlanAddFormRefusals(t *testing.T) {
	const noManualWork = "You do not have permission to add non-school programme activities."
	form, ok := fieldFormFor("/work-plan/add")
	if !ok {
		t.Fatal("not a field form")
	}
	for _, role := range []string{"CCEO", "Program Lead", "CountryDirector", "ImpactAssessment", "HumanResources", "ProjectCoordinator", "Admin"} {
		if got := form.refusal(fieldPrincipal(role)); got != "" {
			t.Fatalf("%s: %q", role, got)
		}
	}
	for _, role := range []string{"Accountant", "RegionalVicePresident", "RegionalProgramLead", "PartnerAdmin", "MfiLoanOfficer", "ClusterLeader"} {
		if got := form.refusal(fieldPrincipal(role)); got != noManualWork {
			t.Fatalf("%s: %q", role, got)
		}
	}
}

func TestWorkPlanAddFormFields(t *testing.T) {
	drawer := workPlanAddDrawer(
		[]programmeChoice{{code: "BOOT_CAMP", name: "Boot Camp", fieldEvent: true}, {code: "CC_SEL", name: "CC-SEL"}},
		[]fieldChoice{{id: "d1", name: "Abim"}},
		"2026-12-01",
	)
	if drawer.GetTitle() != "Plan field event" || drawer.GetSubmitLabel() != "Add to my plan" || !drawer.GetCanSubmit() {
		t.Fatalf("drawer = %q / %q", drawer.GetTitle(), drawer.GetSubmitLabel())
	}
	items := drawer.GetItems()
	if len(items) != 11 {
		t.Fatalf("%d items", len(items))
	}
	activity := items[0].GetField()
	if !activity.GetRequired() || len(activity.GetOptions()) != 3 || activity.GetOptions()[0].GetLabel() != "Select an approved activity" {
		t.Fatalf("activity = %+v", activity)
	}
	if got := activity.GetOptions()[1]; got.GetValue() != "BOOT_CAMP" || got.GetGroup() != "true" {
		t.Fatalf("field event = %+v", got)
	}
	if got := activity.GetOptions()[2]; got.GetGroup() != "false" {
		t.Fatalf("other activity = %+v", got)
	}
	if got := items[1].GetField(); len(got.GetOptions()) != 9 || got.GetOptions()[0].GetLabel() != "Select the intervention being followed up" {
		t.Fatalf("intervention = %+v", got)
	}
	if got := items[2].GetField(); got.GetValue() != "2026-12-01" || !got.GetRequired() || got.GetKind() != "date" {
		t.Fatalf("start = %+v", got)
	}
	if got := items[4].GetField(); got.GetOptions()[0].GetLabel() != "My own district" || got.GetOptions()[1].GetValue() != "d1" {
		t.Fatalf("district = %+v", got)
	}
	if got := items[6].GetField(); got.GetMin() != 1 || got.GetMax() != 10000 {
		t.Fatalf("schools = %+v", got)
	}
	if got := items[7].GetField(); got.GetMin() != 1 || got.GetMax() != 100000 {
		t.Fatalf("participants = %+v", got)
	}
	if items[8].GetText() != "Cost preview" || !strings.HasPrefix(items[10].GetText(), "It appears in My Plan") {
		t.Fatalf("closing lines = %q / %q", items[8].GetText(), items[10].GetText())
	}
}

func TestWorkPlanDatePrefill(t *testing.T) {
	for raw, want := range map[string]string{"": "", " 2026-12-01 ": "2026-12-01", "2026-12-01T09:00": "2026-12-01"} {
		if got := workPlanDatePrefill(raw); got != want {
			t.Fatalf("%q = %q, want %q", raw, got, want)
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
