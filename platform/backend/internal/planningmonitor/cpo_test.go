package planningmonitor

import (
	"testing"
	"time"
)

// window_for: a quarter is three months from its first (Q1 in the year
// before the FY), a month sits in the FY's first calendar year from October,
// a week is seven days from its Monday, anything else the whole year.
func TestCPOWindowFor(t *testing.T) {
	d := func(s string) time.Time { v, _ := time.Parse("2006-01-02", s); return v }
	monday := d("2026-11-23")
	cases := []struct {
		name, period, quarter string
		month                 int
		week                  *time.Time
		start, end            string
		months                []int
	}{
		{"year", "fy", "", 0, nil, "2026-10-01", "2027-10-01", []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}},
		{"Q1", "quarter", "Q1", 0, nil, "2026-10-01", "2027-01-01", []int{1, 2, 3}},
		{"Q3", "quarter", "Q3", 0, nil, "2027-04-01", "2027-07-01", []int{7, 8, 9}},
		{"November", "month", "", 11, nil, "2026-11-01", "2026-12-01", []int{2}},
		{"March", "month", "", 3, nil, "2027-03-01", "2027-04-01", []int{6}},
		{"a week", "week", "", 0, &monday, "2026-11-23", "2026-11-30", nil},
		{"a bad quarter is the year", "quarter", "Q5", 0, nil, "2026-10-01", "2027-10-01", []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}},
	}
	for _, tc := range cases {
		w := cpoWindowFor("2027", tc.period, tc.quarter, tc.month, tc.week)
		if w.start.Format("2006-01-02") != tc.start || w.end.Format("2006-01-02") != tc.end {
			t.Errorf("%s: %s to %s", tc.name, w.start.Format("2006-01-02"), w.end.Format("2006-01-02"))
		}
		if len(w.monthsOfFY) != len(tc.months) {
			t.Errorf("%s: months %v", tc.name, w.monthsOfFY)
		}
	}
	if got := isoWeekStart(2026, 48).Format("2006-01-02"); got != "2026-11-23" {
		t.Errorf("2026-W48 starts %s", got)
	}
}

// allocate: Core staff slots in full, the deficit on the least-planned Core
// schools from the end, and the Client schools staff hold first as far as
// the ceiling's remainder goes; the rest are the Partner's.
func TestAllocateFollowsThePlan(t *testing.T) {
	c := rules.CountryOversight
	owner := &cpoOwner{role: rules.CCEORole, active: true}
	core := func(code string, claims int) *cpoSchool {
		return &cpoSchool{id: code, code: code, family: c.CoreFamily, annualStaffClaims: claims}
	}
	client := func(code, holder string) *cpoSchool {
		return &cpoSchool{id: code, code: code, family: c.ClientFamily, annualHolder: holder}
	}
	ceiling := c.StaffCeilings[rules.CCEORole]
	schools := []*cpoSchool{}
	// Enough Core schools to pass the ceiling by three staff visits.
	n := ceiling/2 + 2
	for i := 0; i < n; i++ {
		schools = append(schools, core("c"+string(rune('a'+i%26))+string(rune('a'+i/26)), 0))
	}
	schools[0].annualStaffClaims = 2
	schools = append(schools, client("z1", "partner"), client("z2", "staff"))
	out := map[string]cpoAllocation{}
	allocate(owner, schools, out)
	deficit := 0
	for _, s := range schools[:n] {
		deficit += out[s.id].deficit
	}
	if deficit != 2*n-ceiling {
		t.Fatalf("deficit %d, want %d", deficit, 2*n-ceiling)
	}
	if out[schools[0].id].deficit != 0 {
		t.Error("the planned Core school carries a deficit")
	}
	if out["z2"].staff != 0 || out["z2"].partner != 1 || out["z1"].partner != 1 {
		t.Errorf("no capacity is left for the Client schools: %v %v", out["z1"], out["z2"])
	}
}

// claims_for: a client-rule school's one slot is staff's when staff plan it,
// and a Partner's dated visit then claims nothing; a Core school's third
// staff visit claims nothing.
func TestClaimsForASchool(t *testing.T) {
	c := rules.CountryOversight
	w := cpoWindowFor("2027", "fy", "", 0, nil)
	client := &cpoSchool{family: c.ClientFamily, schoolType: "client", staff: [4]int{0, 1, 1, 0}}
	client.partnerCounts("p1")[pSchedI], client.partnerCounts("p1")[pSchedT] = 1, 1
	cl := claimsFor(client, cpoAllocation{staff: 1}, w, "", nil)
	if cl.staff != 1 || cl.partnerScheduled != 0 || cl.visitSlots != 1 {
		t.Errorf("client claims %+v", cl)
	}
	core := &cpoSchool{family: c.CoreFamily, schoolType: "core", staff: [4]int{0, 3, 3, 0}}
	cl = claimsFor(core, cpoAllocation{staff: 2, partner: 2}, w, "", nil)
	if cl.staff != 2 || cl.cumStaff != 2 || cl.partnerGap != 2 {
		t.Errorf("core claims %+v", cl)
	}
	if !duplicated(core) {
		t.Error("three staff visits at a Core school are not flagged")
	}
}
