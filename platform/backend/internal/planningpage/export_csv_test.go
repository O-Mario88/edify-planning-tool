package planningpage

import "testing"

func TestTheCSVsReadinessFollowsTheServicesOrder(t *testing.T) {
	ready := school{ClusterID: "c", DistrictID: "d", OwnerID: "o", Code: "1"}
	score := func(f float64) *csvSchool { return &csvSchool{subCounty: "s", hasLatest: true, latestScore: &f} }
	cases := []struct {
		sc        school
		x         *csvSchool
		catalogue bool
		want      [2]string
	}{
		{school{}, &csvSchool{}, true, [2]string{"Cluster Required", "Add to Cluster"}},
		{school{ClusterID: "c"}, &csvSchool{}, true, [2]string{"Data Cleanup Required", "Complete operational details: District, Sub-county, Responsible staff, School ID."}},
		{ready, score(4), false, [2]string{"Cost Catalogue Required", "Ask CD/Admin to activate Cost Catalogue"}},
		{ready, &csvSchool{subCounty: "s", scheduled: true}, true, [2]string{"In My Plan", "Open My Plan"}},
		{ready, &csvSchool{subCounty: "s", hasAssignment: true, assignment: "pending_scheduling"}, true, [2]string{"Partner Pending Schedule", "Monitor Partner Scheduling"}},
		{ready, &csvSchool{subCounty: "s"}, true, [2]string{"SSA Required", "Complete SSA"}},
		{ready, score(4.9), true, [2]string{"Ready for Support", "Recommend Partner (In-school coaching)"}},
		{ready, score(7.9), true, [2]string{"Ready for Support", "Recommend Staff (Visit/training support)"}},
		{ready, score(8), true, [2]string{"Ready for Support", "Maintain/consider champion pathway"}},
	}
	for i, c := range cases {
		r, a := planningReadiness(c.sc, c.x, c.catalogue)
		if [2]string{r, a} != c.want {
			t.Fatalf("case %d: %q %q", i, r, a)
		}
	}
}

func TestTheSSAStatusNamesACollectionToComeBeforeTheLatestRecord(t *testing.T) {
	if got := ssaReadiness(true, "confirmed", "2027", "2027", true, "partner", "school_visit"); got != "Partner Collection Pending" {
		t.Fatal(got)
	}
	if got := ssaReadiness(true, "confirmed", "2026", "2027", false, "", ""); got != "Expired / Needs Refresh" {
		t.Fatal(got)
	}
	if got := ssaReadiness(false, "", "", "2027", false, "", ""); got != "No SSA" {
		t.Fatal(got)
	}
}

func TestTheResponsibleColumnNamesTheKindThenWhoIsMeant(t *testing.T) {
	if got := (responsibility{}).display(); got != "Staff · Unassigned" {
		t.Fatal(got)
	}
	if got := (responsibility{partner: true, name: "Literacy Uganda", stageLabel: "Awaiting Schedule"}); got.display() != "Partner · Literacy Uganda" || got.workflow() != "Awaiting Schedule" {
		t.Fatal(got.display(), got.workflow())
	}
	if got := (responsibility{name: "Paul", returned: true}).workflow(); got != rules.CSVExport.ReturnedLabel {
		t.Fatal(got)
	}
	if got := (responsibility{multiple: true}); got.display() != rules.CSVExport.MultipleLabel || got.workflow() != rules.CSVExport.MultipleLabel {
		t.Fatal(got.display())
	}
}
