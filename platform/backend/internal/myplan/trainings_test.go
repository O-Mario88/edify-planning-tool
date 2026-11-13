package myplan

import (
	"strings"
	"testing"
)

func TestTheTrainingsTableNamesThePlaceAndWhereItWasPlannedFrom(t *testing.T) {
	label := "Cluster Training"
	three := 3
	zero := 0
	cases := []struct {
		name              string
		r                 *planRow
		place, href, from string
		fromHref, people  string
		training, mode    string
	}{
		{"a school a session reached",
			&planRow{row: &row{a: &activity{activityType: "cluster_training", delivery: sp("staff")}, schoolID: schoolID{value: "S1"},
				schoolName: "Hill School", placeURL: "/schools/S1", clusterID: "c1", clusterName: "North", isClusterInvited: true,
				expected: &three, trainingName: "Literacy", trainingMode: "Cluster Group Training", activityTypeLabel: &label}},
			"Hill School", "/schools/S1", "North Invited", "/clusters/c1", "3", "Literacy", "Cluster Group Training"},
		{"a session that reached nobody",
			&planRow{row: &row{a: &activity{activityType: "cluster_training", delivery: sp("staff")}, schoolName: "North",
				placeURL: "/clusters/c1", clusterID: "c1", clusterName: "North", expected: &zero}},
			"North", "/clusters/c1", "North", "/clusters/c1", dash, "Not yet named", dash},
		{"an in-school training",
			&planRow{row: &row{a: &activity{activityType: "in_school_training", delivery: sp("staff")}, schoolID: schoolID{value: "S2"},
				schoolName: "Lake School", placeURL: "/schools/pk2", clusterName: "Lake School"}},
			"Lake School", "/schools/pk2", "School Visit", "", dash, "Not yet named", dash},
		{"a training delivered in school by its delivery (the row carries no delivery)",
			&planRow{row: &row{a: &activity{activityType: "training", delivery: sp("in-school")}, schoolName: "Unknown School",
				clusterName: "Unassigned"}},
			"Unassigned", "", "Unassigned", "", dash, "Not yet named", dash},
		{"a training at no place",
			&planRow{row: &row{a: &activity{activityType: "training", delivery: sp("staff")}, schoolName: "Unknown School",
				clusterName: "Unassigned"}},
			"Unassigned", "", "Unassigned", "", dash, "Not yet named", dash},
		{"a school with no name",
			&planRow{row: &row{a: &activity{activityType: "school_improvement_training", delivery: sp("staff")},
				schoolID: schoolID{value: "S3"}, schoolName: "Unknown School", placeURL: "/schools/pk3", clusterName: "X"}},
			"X", "/schools/pk3", "X", "", dash, "Not yet named", dash},
	}
	for _, c := range cases {
		cells := trainingTableCells(c.r)
		if len(cells) != 13 {
			t.Fatalf("%s: %d cells", c.name, len(cells))
		}
		if cells[1].GetText() != c.place || cells[1].GetHref() != c.href {
			t.Errorf("%s: place %q %q", c.name, cells[1].GetText(), cells[1].GetHref())
		}
		if cells[4].GetText() != c.from || cells[4].GetHref() != c.fromHref {
			t.Errorf("%s: planned from %q %q", c.name, cells[4].GetText(), cells[4].GetHref())
		}
		if cells[6].GetText() != c.training || cells[10].GetText() != c.people || cells[11].GetText() != c.mode {
			t.Errorf("%s: training %q people %q mode %q", c.name, cells[6].GetText(), cells[10].GetText(), cells[11].GetText())
		}
	}
}

func TestAGroupTrainingIsNamedByCourseThenSessionThenPurpose(t *testing.T) {
	named := "G Named"
	cases := []struct {
		name string
		r    *planRow
		want string
	}{
		{"the course", &planRow{row: &row{a: &activity{}, trainingName: "Literacy", purpose: "p"}, x: extra{activityName: &named}}, "Literacy"},
		{"the session's name", &planRow{row: &row{a: &activity{}, purpose: "p"}, x: extra{activityName: &named}}, "G Named"},
		{"the purpose", &planRow{row: &row{a: &activity{}, purpose: "p"}}, "p"},
		{"nothing", &planRow{row: &row{a: &activity{}}}, "Group Training"},
	}
	for _, c := range cases {
		c.r.clusterID, c.r.clusterName = "c1", "North"
		cells := groupTableCells(c.r)
		if cells[6].GetText() != c.want {
			t.Errorf("%s: %q, want %q", c.name, cells[6].GetText(), c.want)
		}
		if cells[0].GetText() != "North" || cells[0].GetHref() != "/clusters/c1" || cells[9].GetText() != "UGX 0" {
			t.Errorf("%s: cells %v", c.name, cells)
		}
	}
}

func TestMyTrainingSummaryDrawsEachFigureAndItsSchools(t *testing.T) {
	five, two, forty := 5, 2, 40
	rows := []TrainingSummaryRow{
		{StaffID: "p1", TrainingID: "t1", TrainingName: "Literacy", Ceiling: &five, InSchool: 3, Partner: 2, PartnerScheduled: 1,
			Group: 1, Total: 5, AwaitingPartner: 1, Balance: &two, Utilization: &forty, State: "available", Flag: "2 below ceiling", FlagTone: "warning"},
		{StaffID: "p1", TrainingID: "t2", TrainingName: "TAM", Group: 4, Total: 4, Excess: 0, State: "unset", Flag: "No ceiling set", FlagTone: "neutral"},
	}
	blocks := summaryBlocks(rows, "2027")
	if len(blocks) != 3 || blocks[0].GetPanel().GetTitle() != "My training summary FY 2027" ||
		blocks[2].GetPanel().GetItems()[0].GetText() != summaryNote {
		t.Fatalf("blocks %v", blocks)
	}
	table := blocks[1].GetTable()
	cols := table.GetColumns()
	if cols[0].GetNumeric() || !cols[1].GetNumeric() || !cols[9].GetNumeric() || cols[10].GetNumeric() {
		t.Errorf("columns %v", cols)
	}
	set, unset := table.GetRows()[0].GetCells(), table.GetRows()[1].GetCells()
	if set[1].GetText() != "5" || set[2].GetHref() != "/training-summary/schools?staff=p1&training=t1&fy=2027&figure=staff" ||
		set[4].GetTone() != "warning" || set[7].GetText() != "2" || !set[7].GetStrong() || set[9].GetText() != "40%" ||
		set[10].GetTone() != "warning" {
		t.Errorf("a training under its ceiling: %v", set)
	}
	if unset[1].GetText() != "Not set" || unset[2].GetText() != "0" || unset[2].GetHref() != "" || unset[7].GetText() != "View" ||
		unset[7].GetStrong() || unset[9].GetText() != dash || unset[6].GetText() != "4" || !unset[6].GetStrong() {
		t.Errorf("a training with no ceiling: %v", unset)
	}
}

func TestThePastDueNoteCountsInTheSentence(t *testing.T) {
	one := pastDueNote(1).GetPanel().GetItems()[0]
	if one.GetText() != "1 planned activity is past its date and not yet completed. It is counted above and listed under What needs you now on the Dashboard, not in the tables below." ||
		one.GetTone() != "warning" || one.GetTextLinks()[0].GetHref() != "/dashboard" {
		t.Errorf("one: %v", one)
	}
	if many := pastDueNote(3).GetPanel().GetItems()[0].GetText(); !strings.HasPrefix(many, "3 planned activities are past their date and not yet completed. They are") {
		t.Errorf("three: %q", many)
	}
}
