package planningmonitor

import "testing"

func TestInListReadsEachListAsTheMonitorDoes(t *testing.T) {
	core := &School{Name: "b", Type: "core", StaffVisits: 1, CorePartnerVisits: 2, CorePartnerTrn: 2}
	booked := &School{Name: "a", Type: "client", StaffVisits: 1, PartnerVisits: 1}
	untouched := &School{Name: "c", Type: "client"}
	champion := &School{Name: "d", Type: "champion"}
	cases := []struct {
		key  string
		s    *School
		want bool
	}{
		{"all", untouched, true},
		{"core", core, true},
		{"client", core, false},
		{"staff_queue", core, true},
		{"staff_visits_left", core, true},
		{"staff_visits_left", booked, false},
		{"client_staff_and_partner", booked, true},
		{"duplicates", booked, true},
		{"core_no_partner_half", core, false},
		{"with_partner", core, true},
		{"partner_left", untouched, true},
		{"partner_visits_left", booked, false},
		{"training_due", champion, false},
		{"not_yet_planned", untouched, true},
		{"fully_planned", champion, true},
		{"no_visit", untouched, true},
		{"not_clustered", untouched, true},
		{"no_ssa", untouched, true},
		{"not_a_list", untouched, true},
	}
	for _, c := range cases {
		if got := inList(c.s, c.key); got != c.want {
			t.Errorf("inList(%s, %q) = %v, want %v", c.s.Name, c.key, got, c.want)
		}
	}
}

func TestListSchoolsAddsOutreachSchoolsButNotToMonitoredLists(t *testing.T) {
	held := &School{Name: "Zebra", Type: "client"}
	other := &School{Name: "apple", Type: "client"}
	outreach := &School{Name: "Mango", Type: "champion"}
	o := &Officer{Schools: []*School{held, other}, Outreach: []*School{outreach}}
	names := func(ss []*School) []string {
		out := []string{}
		for _, s := range ss {
			out = append(out, s.Name)
		}
		return out
	}
	if got := names(listSchools([]*Officer{o}, "all")); len(got) != 3 || got[0] != "apple" || got[1] != "Mango" || got[2] != "Zebra" {
		t.Errorf("all = %v, want [apple Mango Zebra]", got)
	}
	if got := names(listSchools([]*Officer{o}, "not_visited")); len(got) != 2 {
		t.Errorf("not_visited = %v, want the two held schools only", got)
	}
	if got := names(listSchools([]*Officer{o}, "no_visit")); len(got) != 2 {
		t.Errorf("no_visit (a gap) = %v, want the two held schools only", got)
	}
}
