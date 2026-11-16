package planningmonitor

import "testing"

func TestASchoolIsFullyPartlyOrNotYetPlanned(t *testing.T) {
	cases := []struct {
		name   string
		school School
		want   string
	}{
		{"a Champion takes nothing", School{Type: "champion"}, "fully"},
		{"a Client with its visit and training", School{Type: "client", StaffVisits: 1, InSchoolTraining: true}, "fully"},
		{"a Client in a Partner's hands only", School{Type: "client", PartnerPending: 1}, "partly"},
		{"a Client with nothing", School{Type: "client"}, "not_yet"},
		{"a Core school with every half", School{Type: "core", StaffVisits: 2, CorePartnerVisits: 2,
			CoreStaffTrainings: 2, CorePartnerTrn: 2}, "fully"},
		{"a Core school with one staff visit", School{Type: "core", StaffVisits: 1}, "partly"},
		{"a Core school with nothing", School{Type: "core"}, "not_yet"},
	}
	for _, c := range cases {
		if got := schoolState(&c.school); got != c.want {
			t.Errorf("%s: %s, want %s", c.name, got, c.want)
		}
	}
}

func TestAClientSchoolBookedTwiceIsADuplicate(t *testing.T) {
	cases := []struct {
		school School
		want   bool
	}{
		{School{Type: "client", StaffVisits: 1, StaffSSAVisits: 1}, false},
		{School{Type: "client", StaffVisits: 2}, true},
		{School{Type: "client", StaffVisits: 1, PartnerPending: 1}, true},
		{School{Type: "client", PartnerVisits: 2}, true},
		{School{Type: "core", StaffVisits: 3}, false},
	}
	for _, c := range cases {
		if got := isDuplicate(&c.school); got != c.want {
			t.Errorf("%+v: %v, want %v", c.school, got, c.want)
		}
	}
}

func TestAVisitsKindIsItsPurposeThenItsType(t *testing.T) {
	cases := []struct{ kind, purpose, project, delivery, want string }{
		{"school_visit", "", "", "staff", "follow_up"},
		{"school_visit", "in_school_training", "", "staff", "in_school_training"},
		{"school_visit", "ssa_support", "", "staff", "ssa_support"},
		{"school_visit", "ssa_support", "", "partner", ""},
		{"school_visit", "donor_visit", "", "staff", ""},
		{"school_visit", "", "alumni", "staff", ""},
		{"cluster_meeting", "", "", "staff", ""},
	}
	for _, c := range cases {
		if got := visitKind(c.kind, c.purpose, c.project, c.delivery, []string{"alumni"}); got != c.want {
			t.Errorf("%+v: %q, want %q", c, got, c.want)
		}
	}
}

func TestATypeIsNamedByTheRulebook(t *testing.T) {
	for in, want := range map[string]string{"core": "Core", "core_trained": "Core Trained", "": "No type", "new_kind": "New Kind"} {
		if got := typeLabel(in); got != want {
			t.Errorf("%q: %q, want %q", in, got, want)
		}
	}
}
