package visitgate

import "testing"

func coreRules() Rules {
	r := testRules
	r.CompanionPurpose = "in_school_training_delivery_visit"
	r.LockLabels = map[string]string{"staff_visits_complete": "Staff visits complete", "unlocked": "Unlocked"}
	c := CoreRules{
		PackageVisitTypes:           []string{"core_visit", "school_visit", "follow_up_visit", "training_follow_up_visit"},
		PackageTrainingTypes:        []string{"training", "in_school_training", "core_training"},
		DataCollectionVisitTypes:    []string{"school_visit_ssa_collection", "baseline_ssa_visit"},
		DataCollectionVisitPurposes: []string{"ssa_support"},
		OutreachVisitTypes:          []string{"donor_visit", "story_gathering_visit"},
		OutreachVisitPurposes:       []string{"donor_visit", "story_gathering"},
		NonPackageVisitPurposes:     []string{"donor_visit", "story_gathering", "ssa_support"},
		PurposeActivityTypes:        map[string]string{"training_follow_up": "training_follow_up_visit", "ssa_support": "school_visit_ssa_collection"},
		LockPackageComplete:         "staff_visits_complete",
		SlotAllocatedStatuses:       []string{"scheduled", "completed", "partner_scheduled"},
		SlotHandedOverStatus:        "assigned",
		SlotDoneStatuses:            []string{"completed", "ia_verified"},
	}
	c.Caps.StaffVisits, c.Caps.PartnerVisits, c.Caps.StaffTrainings, c.Caps.PartnerTrainings = 2, 2, 2, 2
	r.Core = c
	return r
}

func TestPackageWorkTakesItsSlotByShapeAndDeliverer(t *testing.T) {
	r := coreRules()
	for _, c := range []struct{ kind, purpose, delivery, want string }{
		{"core_visit", "training_follow_up", "staff", "visit"},
		{"in_school_training", "", "staff", "training"},
		{"school_visit", "in_school_training_delivery_visit", "staff", "visit"},
		{"school_visit_ssa_collection", "ssa_support", "staff", "visit"},
		{"school_visit_ssa_collection", "ssa_support", "partner", ""},
		{"donor_visit", "", "staff", ""},
		{"core_visit", "story_gathering", "staff", ""},
	} {
		if got := slotKind(r, c.kind, c.purpose, c.delivery); got != c.want {
			t.Errorf("%s/%s/%s: %q, want %q", c.kind, c.purpose, c.delivery, got, c.want)
		}
	}
	for _, c := range []struct {
		h    handover
		want string
	}{
		{handover{support: " Visit "}, "visit"},
		{handover{trainingNumber: true}, "training"},
		{handover{purpose: "ssa_support"}, ""},
		{handover{purpose: "training_follow_up"}, "visit"},
		{handover{expected: "in_school_training"}, "training"},
		{handover{support: "Visit", universal: true}, ""},
		{handover{support: "Visit", project: "alumni"}, ""},
	} {
		if got := assignmentKind(r, c.h, []string{"alumni"}); got != c.want {
			t.Errorf("%+v: %q, want %q", c.h, got, c.want)
		}
	}
}

func TestACoreSidesTwoCloseItsDoors(t *testing.T) {
	r := coreRules()
	g := gateOf("core")
	g.Split = CoreSplit{HasPackage: true, StaffVisits: 2, PartnerVisits: 1, PartnerPendingVisits: 1, PartnerPendingTrainings: 2}
	g.decideCore(r)
	if g.StaffCanSchedule || g.LockLabel(r) != "Staff visits complete" ||
		g.StaffReason != "Staff core visits complete on this package (2/2). The other 2 visits are the partner's." {
		t.Errorf("the staff side: %+v", g)
	}
	if g.CanAssignPartner || g.AssignReason != "The partner's half of this package is taken: 2/2 visits and 2/2 trainings." {
		t.Errorf("the partner side: %q", g.AssignReason)
	}
	// A school with no package for the year keeps every door open.
	open := gateOf("core")
	open.Split = CoreSplit{StaffVisits: 3}
	open.decideCore(r)
	if !open.StaffCanSchedule || !open.CanAssignPartner || open.LockLabel(r) != "" {
		t.Errorf("no package: %+v", open)
	}
}

func TestASlotReadsDoneTakenOrOpen(t *testing.T) {
	c := coreRules().Core
	for status, want := range map[string]string{"Planned": "open", "Scheduled": "planned", " Assigned ": "planned", "completed": "done", "": "open"} {
		if got := c.SlotState(status); got != want {
			t.Errorf("%q: %s, want %s", status, got, want)
		}
	}
}
