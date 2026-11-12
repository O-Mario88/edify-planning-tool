package activities

import (
	"context"
	"errors"
	"net/url"
	"slices"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The drawer's form is taken only for 31.1's fields, each posted once, and
// read as the view reads it: stripped as Python strips.
func TestTheEditFormIsTakenOnlyForAVisitsWords(t *testing.T) {
	drawer := url.Values{
		"csrfmiddlewaretoken": {"t"}, "purpose_type": {"donor_visit"}, "purpose_training_course_id": {""},
		"scheduled_date": {"2026-11-17"}, "school_id": {"1650"}, "focus_intervention": {""},
		"activity_purpose_text": {" \x1cGoal\n"}, "expected_outcome": {"Outcome"},
	}
	req, ok := EditRequestFromForm("a1", drawer)
	if !ok || req.ActivityID != "a1" || req.Posted["activity_purpose_text"] != "Goal" || req.Reason != "" {
		t.Fatalf("the drawer's form: %v %+v", ok, req)
	}
	if _, seen := req.Posted["csrfmiddlewaretoken"]; seen {
		t.Fatal("the form's token is not a field of the edit")
	}
	for name, form := range map[string]url.Values{
		"a project":            {"project_id": {""}},
		"a training":           {"training_course_id": {"t"}},
		"a facilitator":        {"facilitating_partner_id": {""}},
		"an end date":          {"end_date": {"2026-11-20"}},
		"an invitation list":   {"invited_schools_shown": {"1"}},
		"a training delivered": {"purpose_training_course_id": {"c1"}},
		"a name posted twice":  {"expected_outcome": {"a", "b"}},
	} {
		if _, ok := EditRequestFromForm("a1", form); ok {
			t.Errorf("%s was taken", name)
		}
	}
}

// The audit row's "fields" are the edit's keys for what was posted, sorted,
// a blank date left out (edit_activity_action).
func TestTheEditedFieldsAreTheViewsKeys(t *testing.T) {
	got := editedFields(map[string]string{
		"scheduled_date": "", "school_id": "1", "purpose_type": "x", "purpose_training_course_id": "",
		"focus_intervention": "", "activity_purpose_text": "g", "expected_outcome": "o",
	})
	want := []string{"activityPurposeText", "expectedOutcome", "focusIntervention", "purposeTrainingCourseId",
		"purposeType", "schoolId"}
	if !slices.Equal(got, want) {
		t.Fatalf("fields %v, want %v", got, want)
	}
}

// editing.edit's reading of the form, in its order: the refusals Go makes
// in the existing words, and every change Go hands on.
func TestTheEditRefusesAndHandsOnInTheEditsOrder(t *testing.T) {
	loc, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		t.Fatal(err)
	}
	s := &Service{kampala: loc}
	visit := editedVisit{moved: moved{id: "a1", schoolID: "s1", purpose: "donor_visit",
		plannedDate: time.Date(2026, 11, 17, 0, 0, 0, 0, time.UTC)}, focus: "", schoolCode: "1650"}
	cases := []struct {
		name    string
		posted  map[string]string
		reason  string
		refusal string
		handOn  bool
	}{
		{"the words alone", map[string]string{"scheduled_date": "2026-11-17", "school_id": "1650",
			"purpose_type": "donor_visit", "focus_intervention": "", "activity_purpose_text": "g"}, "", "", false},
		{"no date posted", map[string]string{"expected_outcome": "o"}, "", "", false},
		{"the school by its id", map[string]string{"school_id": "s1"}, "", "", false},
		{"no such day", map[string]string{"scheduled_date": "2026-02-30"}, "", "Invalid date: 2026-02-30", false},
		{"no such day, another school too", map[string]string{"scheduled_date": "2026-13-01", "school_id": "9"}, "",
			"Invalid date: 2026-13-01", false},
		{"a date in another form", map[string]string{"scheduled_date": "2026-11-17T00:00"}, "", "", true},
		{"a new day without a reason", map[string]string{"scheduled_date": "2026-11-18"}, "", editDateReason, false},
		{"a new day and a new purpose without a reason",
			map[string]string{"scheduled_date": "2026-11-18", "purpose_type": "social_visit"}, "", editDateReason, false},
		{"a new day with a reason", map[string]string{"scheduled_date": "2026-11-18"}, "why", "", true},
		{"another school", map[string]string{"school_id": "1286", "scheduled_date": "2026-11-18"}, "", "", true},
		{"another purpose without a reason", map[string]string{"purpose_type": "social_visit"}, "", editPurposeReason, false},
		{"a blank purpose without a reason", map[string]string{"purpose_type": ""}, "", editPurposeReason, false},
		{"another purpose with a reason", map[string]string{"purpose_type": "social_visit"}, "why", "", true},
		{"another focus", map[string]string{"focus_intervention": "leadership"}, "", "", true},
	}
	for _, c := range cases {
		err := s.judgeEdit(&editPlan{a: visit, req: EditRequest{Posted: c.posted, Reason: c.reason}})
		var refusal *Refusal
		switch {
		case c.refusal != "":
			if !errors.As(err, &refusal) || refusal.Message != c.refusal {
				t.Errorf("%s: %v, want the refusal %q", c.name, err, c.refusal)
			}
		case c.handOn:
			if !errors.Is(err, ErrHandOn) {
				t.Errorf("%s: %v, want a hand-on", c.name, err)
			}
		case err != nil:
			t.Errorf("%s: %v, want it taken", c.name, err)
		}
	}
}

// A person in an acting seat, with no staff profile, or asking for visits is
// handed on before anything is read, as is a form naming a training.
func TestTheEditHandsOnBeforeAnyRead(t *testing.T) {
	s := &Service{now: time.Now}
	for name, c := range map[string]struct {
		p   auth.Principal
		req EditRequest
	}{
		"an acting seat":       {auth.Principal{Account: auth.Account{StaffProfileID: "s", InActingAppointment: true}}, EditRequest{}},
		"no staff profile":     {auth.Principal{}, EditRequest{}},
		"a training delivered": {auth.Principal{Account: auth.Account{StaffProfileID: "s"}}, EditRequest{Posted: map[string]string{"purpose_training_course_id": "c"}}},
		"another field":        {auth.Principal{Account: auth.Account{StaffProfileID: "s"}}, EditRequest{Posted: map[string]string{"project_id": ""}}},
	} {
		if _, err := s.Edit(context.Background(), c.p, c.req, Origin{}); !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v, want a hand-on", name, err)
		}
	}
}

func TestPyStripIsPythonsStrip(t *testing.T) {
	for in, want := range map[string]string{
		" a ": "a", "\x1c\x1d a\x1e\x1f": "a", " a　": "a", "​a": "​a", "": "",
	} {
		if got := pyStrip(in); got != want {
			t.Errorf("pyStrip(%q) = %q, want %q", in, got, want)
		}
	}
}
