package teams

import (
	"slices"
	"testing"
)

func someone(id, role string, roles ...string) person {
	return person{StaffID: id, ActiveRole: role, Roles: append([]string{role}, roles...), Country: "Uganda"}
}

func TestTheReportingLineIsTheLinkOfTheRoleThatShouldSupervise(t *testing.T) {
	oversight := link{ID: "ia-link", Supervisor: someone("ia", roleIA)}
	lead := link{ID: "pl-link", Supervisor: someone("pl", roleProgramLead)}
	if line, ok := directLine([]link{oversight, lead}, roleCCEO); !ok || line.ID != "pl-link" {
		t.Fatalf("a CCEO's line is %+v, want the Program Lead's", line)
	}
	if _, ok := directLine([]link{oversight}, roleCCEO); ok {
		t.Fatal("an oversight link was taken for a CCEO's reporting line")
	}
	if line, ok := directLine([]link{oversight, lead}, roleAccountant); !ok || line.ID != "ia-link" {
		t.Fatal("a role without a set supervisor takes its first link")
	}
}

func TestWhoAManagerMayManage(t *testing.T) {
	manager := someone("m", roleProgramLead)
	abroad := someone("abroad", roleCCEO)
	abroad.Country = "Kenya"
	people := []person{someone("c1", roleCCEO), someone("pl2", roleProgramLead), someone("acc", roleAccountant),
		someone("admin", "Admin"), someone("pa", rolePartnerAdm), abroad, manager}
	ids := func(list []person) []string {
		var out []string
		for _, p := range list {
			out = append(out, p.StaffID)
		}
		return out
	}
	if got := ids(eligibleFor(manager, roleProgramLead, people)); !slices.Equal(got, []string{"c1"}) {
		t.Fatalf("a Program Lead manages CCEOs in the country: %v", got)
	}
	if got := ids(eligibleFor(manager, roleCD, people)); !slices.Equal(got, []string{"c1", "pl2", "acc"}) {
		t.Fatalf("a Country Director's team: %v", got)
	}
	if got := ids(eligibleFor(manager, roleIA, people)); !slices.Equal(got, []string{"c1", "pl2", "acc"}) {
		t.Fatalf("Impact Assessment manages Edify staff only, never the Admin or partners: %v", got)
	}
}

func TestTheManagementRolePrefersTheActiveRole(t *testing.T) {
	if role := someone("x", roleCCEO, roleRVP, roleIA).managementRole(); role != roleRVP {
		t.Fatalf("first held management role: %q", role)
	}
	if role := someone("x", roleIA, roleProgramLead).managementRole(); role != roleIA {
		t.Fatalf("the active role first: %q", role)
	}
	if role := someone("x", roleCCEO).managementRole(); role != "" {
		t.Fatalf("a CCEO manages nobody: %q", role)
	}
}

func TestATeamChangeIsSortedIntoAddedRemovedAndMoved(t *testing.T) {
	added, removed, moved := diff([]string{"b", "a", "c"}, map[string]bool{"a": true, "z": true}, map[string]bool{"c": true})
	if !slices.Equal(added, []string{"b", "c"}) || !slices.Equal(removed, []string{"z"}) || !slices.Equal(moved, []string{"c"}) {
		t.Fatalf("added %v removed %v moved %v", added, removed, moved)
	}
	if got := dedupe([]string{" a", "a", "", "b"}); !slices.Equal(got, []string{"a", "b"}) {
		t.Fatalf("dedupe %v", got)
	}
}
