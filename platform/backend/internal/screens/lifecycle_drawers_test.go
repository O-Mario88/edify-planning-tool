package screens

import (
	"encoding/json"
	"reflect"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

// sameJSON compares two JSON texts as values, so key order does not matter.
func sameJSON(t *testing.T, got, want string) bool {
	t.Helper()
	var a, b any
	if err := json.Unmarshal([]byte(got), &a); err != nil {
		t.Fatalf("got is not JSON: %v", err)
	}
	if err := json.Unmarshal([]byte(want), &b); err != nil {
		t.Fatalf("want is not JSON: %v", err)
	}
	return reflect.DeepEqual(a, b)
}

func TestTheStartDrawerReadsAsTheFeedReadsIt(t *testing.T) {
	d := startDrawer(activities.LifecycleFacts{ActivityType: "school_visit", Place: "Central Division Primary School"})
	got, _ := protojson.Marshal(d)
	want := `{"title":"Start school visit at Central Division Primary School","hasRequired":true,"items":[` +
		`{"text":"The activity moves to Started and the team sees that execution has begun."},` +
		`{"field":{"name":"notes","label":"Execution or location notes (optional)","kind":"textarea","placeholder":"e.g. Arrived at the school"}}],` +
		`"submitLabel":"Start activity","cancelLabel":"Cancel","canSubmit":true}`
	if !sameJSON(t, string(got), want) {
		t.Fatalf("got %s", got)
	}
}

func TestTheSalesforceDrawerAsksTheDayWhenItHandsTheVisitIn(t *testing.T) {
	today := time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC)
	d := salesforceDrawer(activities.LifecycleFacts{ActivityType: "school_visit", Place: "Central Division Primary School",
		Status: "scheduled", HandsInWithID: true}, today)
	got, _ := protojson.Marshal(d)
	want := `{"title":"Enter Salesforce ID for Central Division Primary School","hasRequired":true,"items":[` +
		`{"field":{"name":"salesforce_id","label":"Salesforce activity ID","kind":"text","required":true,` +
		`"help":"SV- or SVE- for a visit, TS- for a training, or the record's own Salesforce ID — any one of them.",` +
		`"placeholder":"e.g. SV-11223344, SVE-11223344 or TS-998877"}},` +
		`{"field":{"name":"actual_delivery_date","label":"Date completed","kind":"date","value":"2026-11-24","required":true,` +
		`"help":"Today or an earlier day. Done before its planned day, it moves to this day with its cost, and the planned day is free for other work.",` +
		`"maxDate":"2026-11-24"}}],` +
		`"submitLabel":"Save Salesforce ID","cancelLabel":"Cancel","canSubmit":true}`
	if !sameJSON(t, string(got), want) {
		t.Fatalf("got %s", got)
	}
	delivered := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	held := salesforceDrawer(activities.LifecycleFacts{ActivityType: "school_visit", Place: "X", SalesforceID: "SVE-1",
		Delivered: &delivered, HandsInWithID: true}, today)
	if v := held.GetItems()[0].GetField().GetValue(); v != "SVE-1" {
		t.Fatalf("the ID held: %q", v)
	}
	if v := held.GetItems()[1].GetField().GetValue(); v != "2026-11-20" {
		t.Fatalf("the day done: %q", v)
	}
	if items := salesforceDrawer(activities.LifecycleFacts{ActivityType: "school_visit", Place: "X"}, today).GetItems(); len(items) != 1 {
		t.Fatalf("work already handed in asks no day: %d items", len(items))
	}
}

func TestTheSubmitDrawerSaysWhatIsMissing(t *testing.T) {
	d := submitDrawer(activities.LifecycleFacts{ActivityType: "school_visit", Place: "Central Division Primary School"})
	got, _ := protojson.Marshal(d)
	want := `{"title":"Submit school visit for review","subtitle":"Central Division Primary School","hasRequired":true,"items":[` +
		`{"text":"Readiness"},{"lines":{"facts":[{"label":"Salesforce activity ID linked","value":"Missing"}]}},` +
		`{"note":{"text":"One or more required items are missing. Programme Lead review may return this activity for correction.","tone":"warning"}}],` +
		`"submitLabel":"Submit for review","cancelLabel":"Cancel","canSubmit":true}`
	if !sameJSON(t, string(got), want) {
		t.Fatalf("got %s", got)
	}
	ready := submitDrawer(activities.LifecycleFacts{ActivityType: "donor_visit", Place: "X", SalesforceID: "SVE-1"})
	if ready.GetTitle() != "Submit donor visit for review" || len(ready.GetItems()) != 2 ||
		ready.GetItems()[1].GetLines().GetFacts()[0].GetValue() != "Completed" {
		t.Fatalf("ready: %v", ready)
	}
}
