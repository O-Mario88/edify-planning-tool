package partnerassigned

import "testing"

func str(s string) *string { return &s }

func TestClusterOrGroupWorkIsAnActivityAndOneSchoolIsAVisit(t *testing.T) {
	if !isSchoolScoped(assignment{SchoolID: "s"}) || isSchoolScoped(assignment{SchoolID: "s", ClusterID: "c"}) ||
		isSchoolScoped(assignment{SchoolID: "s", Expected: "cluster_meeting"}) || isSchoolScoped(assignment{}) {
		t.Fatal("scope")
	}
}

func TestTheSubtypeAndPurposeFallBackAsThePageDoes(t *testing.T) {
	if got := subtype(assignment{Item: str("School Visit")}); got != "School Visit" {
		t.Errorf("item %q", got)
	}
	if got := subtype(assignment{Expected: "in_school_training"}); got != "In School Training" {
		t.Errorf("type %q", got)
	}
	if got := purpose(assignment{PurposeCode: "nothing", Purpose: "Free text"}); got != "Free text" {
		t.Errorf("free text %q", got)
	}
	if got := purpose(assignment{}); got != "—" {
		t.Errorf("none %q", got)
	}
}

func TestATeamMemberIsOfferedScheduleAlone(t *testing.T) {
	rows := []assignment{{ID: "a", SchoolID: "s", Item: str("X"), HasItem: true}}
	cells := page(SchoolsPath, true, false, rows, nil).GetBlocks()[0].GetTable().GetRows()[0].GetCells()
	if cells[len(cells)-1].GetText() != "Schedule" {
		t.Fatalf("team member decision %q", cells[len(cells)-1].GetText())
	}
}
