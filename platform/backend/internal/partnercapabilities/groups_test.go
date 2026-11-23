package partnercapabilities

import (
	"reflect"
	"testing"
)

var interventions = [][2]string{{"leadership", "Leadership"}, {"enrolment", "Enrolment"}}

func TestEveryInterventionAndLoanAppearWithNothingInTheCatalogue(t *testing.T) {
	got := buildGroups(interventions, nil, nil)
	want := []Group{
		{Key: "leadership", Label: "Leadership"},
		{Key: "enrolment", Label: "Enrolment"},
		{Key: "loan", Label: "Loan"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v", got)
	}
}

func TestActivitiesSitUnderTheirInterventionInMappingOrder(t *testing.T) {
	items := []Activity{{Code: "A", Name: "Alpha"}, {Code: "B", Name: "Beta"}}
	mappings := []mapping{
		{code: "B", intervention: "leadership", mode: "fixed"},
		{code: "A", intervention: "leadership", mode: "fixed"},
		{code: "A", intervention: "leadership", mode: "multiple_allowed"},
	}
	got := buildGroups(interventions, items, mappings)
	want := []Activity{{Code: "B", Name: "Beta"}, {Code: "A", Name: "Alpha"}}
	if !reflect.DeepEqual(got[0].Activities, want) {
		t.Fatalf("got %+v", got[0].Activities)
	}
}

func TestWorkForAnyInterventionAndUnmappedWorkGetTheirOwnGroups(t *testing.T) {
	items := []Activity{{Code: "A", Name: "Alpha"}, {Code: "B", Name: "Beta"}, {Code: "C", Name: "Gamma"}}
	mappings := []mapping{
		{code: "A", intervention: "leadership", mode: "administrative"},
		{code: "B", mode: "fixed"},
	}
	got := buildGroups(interventions, items, mappings)
	if len(got) != 5 {
		t.Fatalf("groups: %+v", got)
	}
	if got[3].Key != "group:any" || got[3].Label != "Any SSA intervention" || len(got[3].Activities) != 2 {
		t.Fatalf("any: %+v", got[3])
	}
	if got[4].Key != "group:unmapped" || got[4].Label != "Not mapped to an intervention" || got[4].Activities[0].Code != "C" {
		t.Fatalf("unmapped: %+v", got[4])
	}
	if len(got[0].Activities) != 0 {
		t.Fatalf("an administrative mapping names no intervention: %+v", got[0])
	}
}

func TestAMappingToAnInterventionOutsideTheListIsNotDrawn(t *testing.T) {
	items := []Activity{{Code: "A", Name: "Alpha"}}
	got := buildGroups(interventions, items, []mapping{{code: "A", intervention: "retired", mode: "fixed"}})
	if len(got) != 3 {
		t.Fatalf("groups: %+v", got)
	}
}
