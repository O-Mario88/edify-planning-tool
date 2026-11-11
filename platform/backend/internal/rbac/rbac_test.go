package rbac

import (
	"slices"
	"testing"
)

func TestTheMatrixIsTheExistingOne(t *testing.T) {
	if len(Roles()) != 16 || !IsRole("Program Lead") || IsRole("SuperUser") {
		t.Fatalf("roles: %v", Roles())
	}
	// Owner, 2026-10-09: accounts are the Admin's alone.
	for _, role := range Roles() {
		if got, want := Grants(role, UserManage), role == Admin; got != want {
			t.Errorf("%s user.manage = %v", role, got)
		}
	}
	if Grants("Nobody", UserManage) || len(PermissionsFor("Nobody")) != 0 {
		t.Fatal("an unknown role was granted something")
	}
	for _, role := range Roles() {
		if !slices.IsSorted(PermissionsFor(role)) {
			t.Fatalf("%s's keys are not sorted; Grants searches them", role)
		}
	}
}

func TestAnAdminIsNeverACCEO(t *testing.T) {
	if !AdminIsAlsoCCEO([]string{"Admin", "CCEO"}) || AdminIsAlsoCCEO([]string{"Admin", "Program Lead"}) {
		t.Fatal("admin_is_also_cceo")
	}
}
