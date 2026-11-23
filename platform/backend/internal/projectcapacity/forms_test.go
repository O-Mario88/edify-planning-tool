package projectcapacity

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestAStageIsReadFromTheActivitysStatus(t *testing.T) {
	cases := []struct{ status, evidence, want string }{
		{"cancelled", "uploaded", "none"},
		{"not_planned", "", "none"},
		{"ia_verified", "", "completed"},
		{"closed", "", "completed"},
		{"submitted_to_pl", "", "evidence"},
		{"scheduled", "uploaded", "evidence"},
		{"scheduled", "accepted", "evidence"},
		{"in_progress", "none", "started"},
		{"completion_started", "", "started"},
		{"scheduled", "none", "planned"},
		{"", "", "planned"},
	}
	for _, tc := range cases {
		if got := stageOf(tc.status, tc.evidence); got != tc.want {
			t.Errorf("%q/%q: got %q, want %q", tc.status, tc.evidence, got, tc.want)
		}
	}
}

func TestTheFurthestStageDecidesTheBlock(t *testing.T) {
	cases := []struct {
		name     string
		stages   []string
		partner  bool
		wantCode string
	}{
		{name: "nothing begun"},
		{name: "cancelled work only", stages: []string{"none"}},
		{name: "planned", stages: []string{"planned"}, wantCode: "planned"},
		{name: "furthest wins", stages: []string{"planned", "completed", "started"}, wantCode: "completed"},
		{name: "work outranks a partner", stages: []string{"evidence"}, partner: true, wantCode: "evidence"},
		{name: "handed to a partner", partner: true, wantCode: "partner"},
	}
	for _, tc := range cases {
		got := blockFor(tc.stages, tc.partner)
		switch {
		case tc.wantCode == "" && got != nil:
			t.Errorf("%s: blocked by %q", tc.name, got.Code)
		case tc.wantCode != "" && (got == nil || got.Code != tc.wantCode || got.Title != "Cannot withdraw" || got.Message == ""):
			t.Errorf("%s: got %+v, want %q", tc.name, got, tc.wantCode)
		}
	}
}

func TestWhoHoldsAnEnrolmentMayWithdrawIt(t *testing.T) {
	staff := func(user, profile string) auth.Principal {
		return auth.Principal{Account: auth.Account{UserID: user, ActiveRole: "CCEO", StaffProfileID: profile}}
	}
	cases := []struct {
		name string
		who  auth.Principal
		e    enrolmentHolders
		want bool
	}{
		{"its allocation's holder", staff("u1", "s1"), enrolmentHolders{assignedStaff: "s1"}, true},
		{"who added it, by profile", staff("u1", "s1"), enrolmentHolders{assignedBy: "s1"}, true},
		{"who added it, by account", staff("u1", "s1"), enrolmentHolders{assignedBy: "u1"}, true},
		{"someone else", staff("u1", "s1"), enrolmentHolders{assignedStaff: "s2", assignedBy: "u2"}, false},
		{"no staff record", staff("u1", ""), enrolmentHolders{assignedBy: "u1"}, false},
	}
	for _, tc := range cases {
		if got := tc.e.heldBy(tc.who); got != tc.want {
			t.Errorf("%s: got %v", tc.name, got)
		}
	}
}

func TestProjectChoiceNamesItsCode(t *testing.T) {
	if got := projectChoiceLabel(project{Name: "CCSEL", Code: "SP-CCSEL"}); got != "CCSEL (SP-CCSEL)" {
		t.Errorf("with a code: %q", got)
	}
	if got := projectChoiceLabel(project{Name: "CCSEL"}); got != "CCSEL" {
		t.Errorf("no code: %q", got)
	}
}
