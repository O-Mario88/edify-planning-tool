package visitgate

import (
	"strings"
	"testing"
)

var testRules = Rules{
	ClientRuleTypes:    []string{"client", "core_trained", "core_graduate", "champion"},
	CoreRuleTypes:      []string{"core"},
	OneCommitmentTypes: []string{"client", "core_trained", "core_graduate"},
	OutreachOnlyTypes:  []string{"champion"},
	StaffVisitCap:      1,
	LockLabels: map[string]string{
		"awaiting_partner_schedule": "Awaiting schedule from partner",
		"partner_visit_scheduled":   "Partner visit scheduled",
		"staff_visit_scheduled":     "Staff visit scheduled",
		"not_applicable":            "",
		"unlocked":                  "Unlocked",
	},
	SchoolTypeLabels: map[string]string{"champion": "Champion", "client": "Client"},
}

func gateOf(schoolType string) Gate {
	return Gate{
		School: School{ID: "s1", Name: "Hill Primary", Type: schoolType}, FY: "2027", Rule: ruleFor(testRules, schoolType),
		StaffCanSchedule: true, CanAssignVisit: true, CanAssignSSA: true, CanAssignPartner: true,
	}
}

func TestAnOpenYearLocksNothing(t *testing.T) {
	g := gateOf("client")
	g.decide(testRules)
	if g.LockLabel(testRules) != "" || !g.CanAssignPartner || g.StaffReason != "" {
		t.Fatalf("an open year: lock %q, assign %v, reason %q", g.LockLabel(testRules), g.CanAssignPartner, g.StaffReason)
	}
}

func TestAStaffSupportVisitLocksTheYear(t *testing.T) {
	g := gateOf("client")
	g.StaffVisits = 1
	g.decide(testRules)
	if g.LockLabel(testRules) != "Staff visit scheduled" {
		t.Fatalf("lock %q", g.LockLabel(testRules))
	}
	want := "Hill Primary has had its staff support visit (a Training Follow Up or an In-school Training) for FY2027 (1/1)."
	if g.StaffReason != want {
		t.Fatalf("reason %q", g.StaffReason)
	}
	// SSA Support may still go to a partner while the year has no SSA.
	if !g.CanAssignPartner {
		t.Fatal("SSA Support is still open to a partner")
	}

	withSSA := gateOf("client")
	withSSA.StaffVisits, withSSA.HasSSA = 1, true
	withSSA.decide(testRules)
	if withSSA.CanAssignPartner ||
		!strings.HasPrefix(withSSA.AssignReason, "Hill Primary already has its staff support visit for FY2027. It is not handed to a partner for another. ") ||
		!strings.HasSuffix(withSSA.AssignReason, "SSA Support is assigned to a partner only where the year's SSA is still to be collected.") {
		t.Fatalf("both doors closed: %v %q", withSSA.CanAssignPartner, withSSA.AssignReason)
	}
}

func TestAPartnerHoldsTheVisitDatedOrNot(t *testing.T) {
	waiting := gateOf("client")
	waiting.PartnerHoldingPending = 1
	waiting.PartnerNames = []string{"Literacy Uganda"}
	waiting.decide(testRules)
	if waiting.LockLabel(testRules) != "Awaiting schedule from partner" ||
		!strings.HasPrefix(waiting.StaffReason, "Hill Primary is assigned to Literacy Uganda for its support visit in FY2027.") {
		t.Fatalf("waiting: %q %q", waiting.LockLabel(testRules), waiting.StaffReason)
	}

	dated := gateOf("core_trained")
	dated.PartnerHoldingDated = 1
	dated.PartnerNames = []string{"Room to Read", "World Reader"}
	dated.decide(testRules)
	if dated.LockLabel(testRules) != "Partner visit scheduled" || !strings.Contains(dated.StaffReason, "Room to Read and World Reader") {
		t.Fatalf("dated: %q %q", dated.LockLabel(testRules), dated.StaffReason)
	}

	nameless := gateOf("client")
	nameless.PartnerHoldingPending = 1
	nameless.decide(testRules)
	if !strings.Contains(nameless.StaffReason, "assigned to a partner for") {
		t.Fatalf("a partner with no name on record: %q", nameless.StaffReason)
	}
}

func TestAChampionIsNeverHandedToAPartner(t *testing.T) {
	g := gateOf("champion")
	g.PartnerHoldingPending = 1
	g.decide(testRules)
	if g.LockLabel(testRules) != "" {
		t.Fatalf("a Champion school has no support visit to lock: %q", g.LockLabel(testRules))
	}
	want := "Hill Primary is a Champion school. Edify staff deliver its visits and trainings themselves; it is never assigned to a partner."
	if g.CanAssignPartner || g.AssignReason != want {
		t.Fatalf("champion: %v %q", g.CanAssignPartner, g.AssignReason)
	}
}

func TestRulesFollowTheSchoolType(t *testing.T) {
	for schoolType, want := range map[string]string{"client": "client", "champion": "client", "core": "core", "": "none", "other": "none"} {
		if got := ruleFor(testRules, schoolType); got != want {
			t.Errorf("%q: %s, want %s", schoolType, got, want)
		}
	}
}
