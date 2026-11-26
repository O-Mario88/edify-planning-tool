package activities

import (
	"fmt"
	"slices"
	"testing"
)

func TestProjectAssignReadsTheFirstFiftyUniqueIDs(t *testing.T) {
	if got := projectAssignIDs(" a, b ,a,,c "); !slices.Equal(got, []string{"a", "b", "c"}) {
		t.Fatalf("ids %q", got)
	}
	raw := ""
	for i := range 60 {
		raw += fmt.Sprintf("id%d,", i)
	}
	if got := projectAssignIDs(raw); len(got) != projectAssignLimit || got[49] != "id49" {
		t.Fatalf("limit: %d %q", len(got), got[len(got)-1])
	}
}

func TestTheProjectAssignConfirmationSaysWhatWasHandedOverSkippedAndRefused(t *testing.T) {
	cases := []struct {
		count, skipped int
		refused        []string
		want           string
	}{
		{1, 0, nil, "Assigned 1 project school to Room to Read. The partner schedules it from here."},
		{2, 1, nil, "Assigned 2 project schools to Room to Read. The partner schedules them from here. 1 school was already assigned to Room to Read and left as they were."},
		{0, 2, nil, "No school was assigned to Room to Read. 2 schools were already assigned to Room to Read and left as they were."},
		{0, 0, []string{"Kito: refused", "Goma: refused"}, "No school was assigned to Room to Read. Not assigned: Kito: refused; Goma: refused"},
	}
	for _, c := range cases {
		if got := projectAssignedMessage(c.count, "Room to Read", c.skipped, c.refused); got != c.want {
			t.Fatalf("got %q\nwant %q", got, c.want)
		}
	}
}

func TestAProjectHandOverRecordsTheProjectsPrimaryInterventionUnlessGeneralIsItsTarget(t *testing.T) {
	measured := ProjectAssignRow{intervention: "leadership", targets: []string{"christlike_behaviour", "leadership"}}
	if got := measured.projectFocus("", "training_follow_up"); got != "leadership" {
		t.Fatalf("the explicit intervention leads: %q", got)
	}
	if got := measured.projectFocus("teaching_environment", "training_follow_up"); got != "teaching_environment" {
		t.Fatalf("the chosen focus stands: %q", got)
	}
	if got := measured.projectFocus("", "ssa_support"); got != "" {
		t.Fatalf("SSA Support moves no intervention: %q", got)
	}
	general := ProjectAssignRow{targets: []string{rules.GeneralIntervention}}
	if general.measured() || general.projectFocus("leadership", "training_follow_up") != "" {
		t.Fatal("a General-only project is measured by no SSA intervention")
	}
	untargeted := ProjectAssignRow{}
	if !untargeted.measured() || untargeted.primary() != "" {
		t.Fatal("a project naming no target is measured like any other, with no primary")
	}
	legacy := ProjectAssignRow{intervention: "learning_environment"}
	if legacy.primary() != "learning_environment" {
		t.Fatalf("a legacy single intervention is the primary: %q", legacy.primary())
	}
}
