package screens

import (
	"slices"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

func fieldsOf(d *screensv1.PageDrawer) map[string]*screensv1.DrawerField {
	out := map[string]*screensv1.DrawerField{}
	for _, item := range d.GetItems() {
		if f := item.GetField(); f != nil {
			out[f.GetName()] = f
		}
	}
	return out
}

// A meeting's drawer is the template's as the feed reads it: the day held,
// the Training ID, the head counts, the register (with the "Select all" box
// the feed reads as an unnamed option) and the notes.
func TestAMeetingsCompleteDrawerIsTheTemplates(t *testing.T) {
	d := completionDrawer(activities.CompleteFacts{
		ActivityID: "m1", ActivityType: "cluster_meeting", Delivered: "2026-11-25", Today: "2026-11-25",
		SalesforceKind: "training", Attendance: true, Cluster: true, Teachers: "0", Leaders: "2",
		Register: []activities.RegisterSchool{{ID: "s1", Name: "A", Code: "1", Ticked: true}, {ID: "s2", Name: "B", Code: "2"}},
	}, true)
	if d.GetTitle() != "Complete cluster meeting" || d.GetSubmitLabel() != "Submit completion" {
		t.Fatalf("title %q submit %q", d.GetTitle(), d.GetSubmitLabel())
	}
	f := fieldsOf(d)
	if got := f["actual_delivery_date"]; got.GetLabel() != "Date the meeting was held" || got.GetMaxDate() != "2026-11-25" || !got.GetRequired() {
		t.Errorf("date %v", got)
	}
	if got := f["salesforce_id"]; got.GetLabel() != "Training ID" || got.GetPlaceholder() != "e.g. TS-998877" {
		t.Errorf("ID %v", got)
	}
	if f["leaders_attended"].GetValue() != "2" || f["teachers_attended"].GetMin() != 0 {
		t.Errorf("counts %v %v", f["teachers_attended"], f["leaders_attended"])
	}
	if got := f["q"]; got.GetReloadsPath() != "/my-plan/m1/register-school-search" || got.GetHelp() != registerAddHelp || got.GetReloadsTarget() != "" {
		t.Errorf("search %v", got)
	}
	register := f["attended_school_ids"]
	values := []string{}
	for _, o := range register.GetOptions() {
		values = append(values, o.GetValue())
	}
	if register.GetValue() != "s1" || !slices.Equal(values, []string{"s1", "s2", "on"}) || register.GetOptions()[1].GetDetail() != "2" {
		t.Errorf("register %v", register)
	}
	if f["actual_observations"].GetMaxLength() != 2000 || f["follow_up_note"].GetLabel() != "Follow-up needed (optional)" {
		t.Errorf("notes %v %v", f["actual_observations"], f["follow_up_note"])
	}
	if help := fieldsOf(completionDrawer(activities.CompleteFacts{ActivityType: "cluster_meeting", Attendance: true, Cluster: true}, false))["q"].GetHelp(); help != "" {
		t.Errorf("a reader who may not add a school is told %q", help)
	}
}

// A visit's drawer asks the day visited and the Visit ID, and no head count.
func TestAVisitsCompleteDrawerIsTheTemplates(t *testing.T) {
	d := completionDrawer(activities.CompleteFacts{
		ActivityType: "school_visit", SchoolName: "Central Division Primary School", Delivered: "2026-11-25",
		Today: "2026-11-25", SalesforceKind: "visit",
	}, true)
	if d.GetTitle() != "Complete school visit at Central Division Primary School" {
		t.Fatalf("title %q", d.GetTitle())
	}
	f := fieldsOf(d)
	if f["actual_delivery_date"].GetLabel() != "Date the school was visited" || f["salesforce_id"].GetLabel() != "Visit ID" {
		t.Errorf("fields %v", f)
	}
	if _, ok := f["teachers_attended"]; ok {
		t.Error("a visit is asked its head count")
	}
}

// The register's ticks come as one comma-joined value from the app.
func TestTheRegistersTicksAreSplit(t *testing.T) {
	if got := ticks("s1,,s2"); !slices.Equal(got, []string{"s1", "s2"}) {
		t.Fatalf("%v", got)
	}
}
