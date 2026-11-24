package screens

import (
	"testing"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

func TestTheBulkScheduleDrawerReadsAsTheFeedReadsIt(t *testing.T) {
	one := []activities.TickedSchool{{Name: "Central Division Church of Uganda Primary", Code: "1442"}}
	got, _ := protojson.Marshal(bulkScheduleDrawer(one, 0, false, false))
	options := `{"label":"Select purpose…"},{"value":"in_school_training","label":"In-school Training"},` +
		`{"value":"in_school_training_ssa","label":"In-school Training + SSA Collection"},` +
		`{"value":"training_follow_up","label":"Training Follow Up"},{"value":"ssa_support","label":"SSA Support"},` +
		`{"value":"donor_visit","label":"Donor Visit"},{"value":"story_gathering","label":"Content/Story Collection"},` +
		`{"value":"school_invitation","label":"School Invitation"},{"value":"social_visit","label":"Social Visit"}`
	want := `{"title":"Schedule 1 school","hasRequired":true,"items":[{"text":"Selected schools"},` +
		`{"text":"Central Division Church of Uganda Primary 1442"},` +
		`{"field":{"name":"purpose_of_visit","label":"Purpose of visit","kind":"select","required":true,"options":[` + options + `]}},` +
		`{"field":{"name":"scheduled_date","label":"Delivery date","kind":"date","required":true}},` +
		`{"note":{"text":"` + bulkScheduleNote + `","tone":"warning"}}],` +
		`"submitLabel":"Schedule 1 school","cancelLabel":"Cancel","canSubmit":true}`
	if !sameJSON(t, string(got), want) {
		t.Fatalf("got %s", got)
	}
	none, _ := protojson.Marshal(bulkScheduleDrawer(nil, 1, false, false))
	if !sameJSON(t, string(none), `{"title":"Schedule 0 schools","hasRequired":true,"items":[{"text":"Selected schools"},`+
		`{"text":"1 selected school is outside your planning portfolio and left out."}],"cancelLabel":"Cancel"}`) {
		t.Fatalf("none: %s", none)
	}
	visitsOnly := bulkScheduleDrawer(one, 0, true, true)
	for _, option := range visitsOnly.GetItems()[2].GetField().GetOptions() {
		switch option.GetValue() {
		case "in_school_training", "in_school_training_ssa", "training_follow_up":
			t.Fatalf("%s is offered", option.GetValue())
		}
	}
}
