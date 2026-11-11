package accounts

import (
	"slices"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func as(role string) auth.Principal {
	return auth.Principal{Account: auth.Account{UserID: "u-actor", ActiveRole: role, Roles: []string{role}}}
}

func TestOnlyAnAdminTouchesAnAdminOrGrantsTheAdminRole(t *testing.T) {
	cases := []struct {
		name            string
		actor           string
		target, request []string
		want            string
	}{
		{"an Admin edits an Admin", "Admin", []string{"Admin"}, nil, ""},
		{"an Admin grants Admin", "Admin", nil, []string{"Admin"}, ""},
		{"HR edits an Admin", "HumanResources", []string{"Admin"}, nil, msgOnlyAdminModifiesAdmin},
		{"HR grants Admin", "HumanResources", []string{"CCEO"}, []string{"Admin"}, msgOnlyAdminGrantsAdmin},
		{"HR edits a CCEO", "HumanResources", []string{"CCEO"}, []string{"Program Lead"}, ""},
	}
	for _, tc := range cases {
		if got := mayAdminister(as(tc.actor), tc.target, tc.request); got != tc.want {
			t.Errorf("%s: %q, want %q", tc.name, got, tc.want)
		}
	}
}

func TestTheOpeningRoleComesFirstAndDuplicatesGo(t *testing.T) {
	got := rolesOf("Program Lead", []string{"CCEO", "Program Lead", "", "CCEO"})
	if !slices.Equal(got, []string{"Program Lead", "CCEO"}) {
		t.Fatalf("roles %v", got)
	}
	if unknownRole([]string{"CCEO", "Overlord"}) != "Overlord" || unknownRole([]string{"CCEO"}) != "" {
		t.Fatal("an unknown role was not named")
	}
	if !sameSet([]string{"A", "B"}, []string{"B", "A"}) || sameSet([]string{"A"}, []string{"A", "B"}) {
		t.Fatal("sameSet")
	}
}

func TestANewAccountWithoutAPasswordCannotSignInUntilInvited(t *testing.T) {
	stored, err := storedPassword("")
	if err != nil || stored[0] != '!' || len(stored) < 30 {
		t.Fatalf("unusable password %q %v", stored, err)
	}
	chosen, err := storedPassword("Edify#2026")
	if err != nil || chosen[:7] != "bcrypt$" {
		t.Fatalf("chosen password stored as %q", chosen)
	}
}
