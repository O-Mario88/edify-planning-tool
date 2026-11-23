package coreforms

import (
	"reflect"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func labels(slots []Slot) []string {
	out := make([]string, len(slots))
	for i, slot := range slots {
		out[i] = slot.Label
	}
	return out
}

func TestAYearNotMadeYetOffersEverySlotWithoutWritingIt(t *testing.T) {
	got := unmadePackage()
	if !got.Available || got.Complete {
		t.Fatalf("package: %+v", got)
	}
	want := []string{"First Visit", "Second Visit", "Third Visit", "Fourth Visit"}
	if !reflect.DeepEqual(labels(got.Visits), want) {
		t.Fatalf("visits: %v", labels(got.Visits))
	}
	if got.Trainings[3].Label != "Fourth Training" || got.Trainings[3].Sequence != 4 {
		t.Fatalf("trainings: %+v", got.Trainings)
	}
}

func TestATakenSlotIsNotOffered(t *testing.T) {
	rules := schoolprofile.GateRules().Core
	got := packageFrom(rules, 4, 4, []slotRow{
		{kind: "visit", sequence: 1, status: "Scheduled"},
		{kind: "visit", sequence: 2, status: "assigned"},
		{kind: "visit", sequence: 3, status: "Planned"},
		{kind: "training", sequence: 1, status: "Planned"},
		{kind: "assessment", sequence: 1, status: "Scheduled"},
	})
	if !reflect.DeepEqual(labels(got.Visits), []string{"Third Visit"}) {
		t.Fatalf("visits: %v", labels(got.Visits))
	}
	if !reflect.DeepEqual(labels(got.Trainings), []string{"First Training"}) || got.Complete {
		t.Fatalf("trainings: %+v", got)
	}
}

func TestAPackageIsCompleteOnceEveryTargetIsTaken(t *testing.T) {
	rules := schoolprofile.GateRules().Core
	var rows []slotRow
	for sequence := 1; sequence <= 2; sequence++ {
		rows = append(rows, slotRow{kind: "visit", sequence: sequence, status: "scheduled"},
			slotRow{kind: "training", sequence: sequence, status: "assigned"})
	}
	if got := packageFrom(rules, 2, 2, rows); !got.Complete {
		t.Fatalf("package: %+v", got)
	}
	if got := packageFrom(rules, 0, 0, rows); got.Complete {
		t.Fatal("a blank target is four, as the existing rule reads it")
	}
}

func TestWhoMayPlanASchool(t *testing.T) {
	own := schooldirectory.Scope{OwnSchoolIDs: []string{"s1"}}
	if !mayPlanSchool("CCEO", own, "s1") || mayPlanSchool("CCEO", own, "s2") {
		t.Fatal("a CCEO plans their own schools")
	}
	for _, role := range []string{"CountryDirector", "ImpactAssessment", "Admin"} {
		if !mayPlanSchool(role, schooldirectory.Scope{CountryScope: true}, "s2") {
			t.Errorf("%s schedules across the country", role)
		}
	}
	if mayPlanSchool("Accountant", schooldirectory.Scope{CountryScope: true, OwnSchoolIDs: []string{"s1"}}, "s1") {
		t.Error("a country-wide reader plans nothing")
	}
}

func TestOnlyTheFourWeakestSSANeedsAreRecommended(t *testing.T) {
	rows := []Need{{"a", "A", 3}, {"b", "B", 4}, {"c", "C", 5}, {"d", "D", 6}, {"e", "E", 7}}
	if got := recommended(rows); len(got) != 4 || got[3].Label != "D" {
		t.Fatalf("got %+v", got)
	}
	if got := recommended([]Need{{"a", "A", 8}, {"b", "B", 9.5}}); len(got) != 0 {
		t.Fatalf("a strong school is told to maintain: %+v", got)
	}
	if got := recommended(nil); len(got) != 0 {
		t.Fatalf("no SSA: %+v", got)
	}
}

func TestCoursesPutStandardSupportFirstThenByName(t *testing.T) {
	got := sortCourses([]Course{
		{Label: "beta", Code: "B"}, {Label: "Zeta", Code: "Z", standard: true},
		{Label: "Alpha", Code: "A"}, {Label: "alpha", Code: "A0"},
	})
	want := []string{"Z", "A", "A0", "B"}
	for i, code := range want {
		if got[i].Code != code {
			t.Fatalf("got %+v", got)
		}
	}
}

func TestACourseCarriesItsPrimaryMappingsIntervention(t *testing.T) {
	cases := []struct {
		name     string
		mappings []courseMapping
		label    string
		chooses  bool
	}{
		{"no mapping", nil, "Not SSA-scored", false},
		{"fixed", []courseMapping{{intervention: "leadership", mode: "fixed", primary: true}}, "Leadership", false},
		{"the primary wins", []courseMapping{{intervention: "enrolment", mode: "fixed"}, {intervention: "leadership", mode: "fixed", primary: true}}, "Leadership", false},
		{"any intervention", []courseMapping{{mode: "any_ssa_intervention", primary: true}}, "Not SSA-scored", true},
		{"administrative", []courseMapping{{mode: "administrative", primary: true}}, "Not SSA-scored", false},
	}
	names := map[string]string{"leadership": "Leadership", "enrolment": "Enrolment"}
	for _, tc := range cases {
		var course Course
		course.applyMappings(tc.mappings, names)
		if course.InterventionLabel != tc.label || course.PlannerChooses != tc.chooses {
			t.Errorf("%s: %+v", tc.name, course)
		}
	}
}

func TestAFollowUpSaysWhatWhenAndWhere(t *testing.T) {
	day := time.Date(2026, 10, 9, 0, 0, 0, 0, time.UTC)
	cases := []struct {
		row  trainingDone
		want string
	}{
		{trainingDone{snapshot: "Budgeting", kind: "in_school_training", day: &day, status: "completed"}, "Budgeting · 09 Oct 2026 · At the school"},
		{trainingDone{catalogue: "Budgeting", kind: "cluster_training", cluster: "Goma", status: "submitted_to_pl"}, "Budgeting · Date not recorded · Goma · awaiting verification"},
		{trainingDone{kind: "cluster_meeting", typeLabel: "Cluster Meeting", day: &day, status: "closed"}, "Cluster Meeting · 09 Oct 2026 · Cluster session"},
	}
	for _, tc := range cases {
		if got := tc.row.label(); got != tc.want {
			t.Errorf("got %q, want %q", got, tc.want)
		}
	}
}
