package leaveapprovals

import (
	"testing"
	"time"
)

func str(s string) *string { return &s }

func TestTheApprovalLadder(t *testing.T) {
	lead := reviewer{userID: "u-pl", role: "pl", hasProfileRow: true, country: str("Uganda"),
		supervised: map[string]bool{"s-cceo": true}, policyFloor: map[string]int{"maternity_leave": 3}}
	officer := leave{staffID: "s-cceo", staffUser: "u-cceo", staffRole: "CCEO", kind: "sick_leave", status: "pending"}
	if !lead.authorized(officer) {
		t.Error("a lead decides their officer's leave")
	}
	if lead.authorized(leave{staffID: "s-other", staffRole: "CCEO", kind: "sick_leave"}) {
		t.Error("a lead does not decide another lead's officer")
	}
	maternity := officer
	maternity.kind = "maternity_leave"
	if lead.authorized(maternity) {
		t.Error("a Country Director floor keeps a lead out")
	}
	own := officer
	own.staffUser = "u-pl"
	if lead.authorized(own) {
		t.Error("no one decides their own leave")
	}
	cd := reviewer{userID: "u-cd", role: "cd", hasProfileRow: true, country: str("Uganda"), supervised: map[string]bool{}, policyFloor: map[string]int{}}
	if !cd.authorized(leave{staffRole: "Program Lead", staffCountry: str("Uganda"), kind: "sick_leave"}) ||
		cd.authorized(leave{staffRole: "Program Lead", staffCountry: str("Kenya"), kind: "sick_leave"}) {
		t.Error("a Country Director decides their country's leads")
	}
	hr := reviewer{userID: "u-hr", role: "hr", hasProfileRow: true, supervised: map[string]bool{}, policyFloor: map[string]int{"sick_leave": 2}}
	if !hr.authorized(leave{staffRole: "Program Lead", kind: "sick_leave", status: "hr_review"}) {
		t.Error("HR decides an escalated request whatever its floor")
	}
	admin := reviewer{userID: "u-a", role: "admin", hasProfileRow: true}
	if admin.authorized(officer) {
		t.Error("Admin decides no leave")
	}
	noProfile := lead
	noProfile.hasProfileRow = false
	if noProfile.authorized(officer) {
		t.Error("a reviewer with no People record decides nothing")
	}
}

func TestTheReadHelpersFollowTheTemplate(t *testing.T) {
	if normalizeRole("Program Lead") != "pl" || normalizeRole("CountryDirector") != "cd" || normalizeRole("Admin") != "admin" {
		t.Error("normalizeRole")
	}
	if selectValue("cancelled", statusOptions) != "pending" || selectValue("", [][2]string{{"", ""}, {"a", "A"}}) != "" {
		t.Error("selectValue")
	}
	if pyTitle("hr_review") != "Hr_Review" || title("personal_time_off") != "Personal Time Off" {
		t.Errorf("titles: %q %q", pyTitle("hr_review"), title("personal_time_off"))
	}
	if apMonth(time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)) != "Sept." || pyRound(50) != 50 || pyRound(2.5) != 2 || pyRound(3.5) != 4 {
		t.Error("apMonth / pyRound")
	}
}
