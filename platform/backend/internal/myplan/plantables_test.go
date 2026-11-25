package myplan

import (
	"testing"
	"time"
)

func sp(s string) *string { return &s }

func TestUnportedRowsLeaveThePageToTheExistingApplication(t *testing.T) {
	cases := []struct {
		name     string
		a        activity
		x        extra
		awaiting bool
		passed   bool
	}{
		{"completed", activity{status: "completed"}, extra{}, false, false},
		{"cancelled", activity{status: "cancelled"}, extra{}, false, false},
		{"still to deliver", activity{status: "scheduled"}, extra{}, false, false},
		{"rescheduled", activity{status: "rescheduled"}, extra{}, false, false},
		{"sent back", activity{status: "returned_by_pl"}, extra{}, false, false},
		{"handed in", activity{status: "submitted_to_pl"}, extra{}, false, false},
		{"verified by IA", activity{status: "ia_verified"}, extra{}, false, false},
		{"disbursed", activity{status: "completed"}, extra{payment: sp("disbursed")}, false, false},
		{"a partner's delivery", activity{status: "completed", delivery: sp("partner")}, extra{}, false, true},
		// An SSA visit awaiting its scores is drawn: the row is open work
		// with its Enter SSA Scores action.
		{"awaiting SSA scores", activity{status: "completed"}, extra{}, true, false},
		{"a training meeting", activity{status: "completed"}, extra{meetingKind: sp("training")}, false, true},
	}
	for _, c := range cases {
		if got := unportedRow(&c.a, &c.x) != ""; got != c.passed {
			t.Errorf("%s: passed %v, want %v", c.name, got, c.passed)
		}
	}
}

func TestTableOfFollowsTheLoopsOrder(t *testing.T) {
	slots := coreSlots{kind: map[string]string{"slotted": "visit"}}
	core := func(id, kind string) *activity {
		return &activity{id: id, activityType: kind, hasSchool: true, schoolType: sp("core")}
	}
	cases := []struct {
		name string
		a    *activity
		want int
	}{
		{"a Core school's visit", core("a", "school_visit"), tableCoreVisits},
		{"a Core school's slotted visit", core("slotted", "school_visit"), -1},
		{"a Core school's training", core("b", "in_school_training"), -1},
		{"a client visit", &activity{activityType: "follow_up_visit", hasSchool: true, schoolType: sp("client")}, tableSchoolVisits},
		{"a meeting at a cluster", &activity{activityType: "cluster_meeting", hasCluster: true}, tableMeetings},
		{"a meeting at no cluster", &activity{activityType: "cluster_meeting"}, -1},
		{"programme work", &activity{activityType: "school_visit", planningSource: sp("manual_work_plan")}, -1},
		{"a training at a cluster", &activity{activityType: "cluster_training", hasCluster: true}, tableTrainings},
		{"an in-school training", &activity{activityType: "in_school_training", hasSchool: true, schoolType: sp("client")}, tableTrainings},
		{"a training at no place", &activity{activityType: "training"}, tableTrainings},
		{"a Champion school's training", &activity{activityType: "in_school_training", hasSchool: true, schoolType: sp("champion")}, tableProgrammeSchool},
		{"a Champion school's visit", &activity{activityType: "school_visit", hasSchool: true, schoolType: sp("champion")}, tableProgrammeSchool},
	}
	for _, c := range cases {
		if got := tableOf(c.a, slots); got != c.want {
			t.Errorf("%s: %d, want %d", c.name, got, c.want)
		}
	}
}

func TestNextIsSubmitWaitsForTheIDTheFormAndThePeople(t *testing.T) {
	four := 4
	cases := []struct {
		name string
		a    activity
		x    extra
		want bool
	}{
		{"completed with an ID", activity{status: "completed", activityType: "school_visit", salesforce: sp("SVE-1")}, extra{evidence: sp("none")}, true},
		{"completed without one", activity{status: "completed", activityType: "school_visit"}, extra{evidence: sp("none")}, false},
		{"in progress", activity{status: "in_progress", activityType: "school_visit", salesforce: sp("SVE-1")}, extra{evidence: sp("uploaded")}, false},
		{"started, no form", activity{status: "completion_started", activityType: "school_visit", salesforce: sp("SVE-1")}, extra{evidence: sp("none")}, false},
		{"started, form in", activity{status: "completion_started", activityType: "school_visit", salesforce: sp("SVE-1")}, extra{evidence: sp("uploaded")}, true},
		{"form accepted", activity{status: "completed", activityType: "school_visit", salesforce: sp("SVE-1")}, extra{evidence: sp("accepted")}, false},
		{"a meeting nobody attended", activity{status: "completed", activityType: "cluster_meeting", salesforce: sp("TS-1")}, extra{evidence: sp("none")}, false},
		{"a meeting attended", activity{status: "completed", activityType: "cluster_meeting", salesforce: sp("TS-1"), teachersAttended: &four}, extra{evidence: sp("none")}, true},
		{"closed", activity{status: "closed", activityType: "school_visit", salesforce: sp("SVE-1")}, extra{evidence: sp("uploaded")}, false},
	}
	for _, c := range cases {
		next, _ := computeNextAction(&c.a, &c.x, nil, time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC))
		if got := next.action == "submit"; got != c.want {
			t.Errorf("%s: %v, want %v", c.name, got, c.want)
		}
	}
}

func TestARowsTintTickAndActions(t *testing.T) {
	today := time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC)
	past := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)
	r := &planRow{row: &row{a: &activity{id: "x", status: "in_progress", plannedDate: &past, delivery: sp("staff"), activityType: "cluster_meeting"}}}
	r.settle(today)
	if r.rowState != "overdue" || !r.canPick {
		t.Fatalf("in progress, past its day: %q, tick %v", r.rowState, r.canPick)
	}
	labels := []string{}
	for _, a := range r.actions().GetActions() {
		labels = append(labels, a.GetKey()+" "+a.GetLabel())
	}
	want := []string{"menu View Details", "menu Reschedule Activity", "menu Change Facilitator", "menu Complete Activity", "danger Cancel Activity"}
	if len(labels) != len(want) {
		t.Fatalf("actions %v", labels)
	}
	for i := range want {
		if labels[i] != want[i] {
			t.Errorf("action %d: %q, want %q", i, labels[i], want[i])
		}
	}
	r.a.status = "deferred"
	r.rowState = ""
	r.settle(today)
	if r.rowState != "" {
		t.Errorf("deferred work is never overdue: %q", r.rowState)
	}
	done := &planRow{row: &row{a: &activity{id: "y", status: "completed", delivery: sp("staff")}, isComplete: true}}
	done.settle(today)
	cell := done.actions()
	if done.rowState != "done" || done.canPick || len(cell.Actions) != 1 || cell.Actions[0].GetReason() != "View Completed Activity" {
		t.Errorf("complete work: %q tick %v actions %v", done.rowState, done.canPick, cell.Actions)
	}
	partner := &planRow{row: &row{a: &activity{id: "z", status: "cancelled", delivery: sp("")}}}
	partner.settle(today)
	if cell := partner.actions(); cell.Text != "Monitoring — partner-owned" || len(cell.Actions) != 1 || partner.canPick {
		t.Errorf("not staff's to deliver: %+v tick %v", cell, partner.canPick)
	}
}

func TestPlannedDistrictAndMeetingPurpose(t *testing.T) {
	r := &planRow{row: &row{a: &activity{hasCluster: true, clusterDistrictID: sp("d"), eventDistrictID: sp("e")}}, x: extra{clusterDistrict: sp("Mukono"), eventDistrict: sp("Wakiso")}}
	if got := r.plannedDistrict(); got != "Mukono" {
		t.Errorf("a cluster session: %q", got)
	}
	r.x.clusterDistrict = sp("")
	if got := r.plannedDistrict(); got != "Wakiso" {
		t.Errorf("a cluster with no district's name, at an event district: %q", got)
	}
	label := "Cluster Meeting"
	m := &planRow{row: &row{purpose: "Cluster Meeting", activityTypeLabel: &label}, x: extra{meetingKind: sp("cluster_leaders")}}
	if got := meetingPurpose(m); got != "Cluster Leaders Meeting" {
		t.Errorf("kind alone: %q", got)
	}
	m.purpose = "Reading"
	if got := meetingPurpose(m); got != "Cluster Leaders Meeting · Reading" {
		t.Errorf("kind and topic: %q", got)
	}
	m.x.meetingKind = nil
	if got := meetingPurpose(m); got != "Reading" {
		t.Errorf("no kind: %q", got)
	}
	for status, want := range map[string]string{"Cost Setup Required": "amber", "Request Returned": "red", "Disbursed": "green", "No Budget": "slate", "In Training": "blue"} {
		if got := budgetColour(status); got != want {
			t.Errorf("%s: %s", status, got)
		}
	}
}
