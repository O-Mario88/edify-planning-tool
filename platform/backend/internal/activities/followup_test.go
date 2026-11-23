package activities

import (
	"reflect"
	"testing"
)

func TestAFollowUpSourceMustBeDeliveredWorkAtThisSchoolThisYear(t *testing.T) {
	const (
		wrongKind  = "Training Follow Up must reference a completed training or cluster meeting this School took part in."
		notDone    = "Follow-up requires a completed source Training or support Activity."
		otherYear  = "Training Follow Up must reference a session from the same Fiscal Year as the scheduled visit."
		notThere   = "This School is not recorded as attending the selected Cluster Training or Cluster Meeting."
		otherPlace = "The selected training was delivered at a different School."
	)
	training := followedSession{Type: "in_school_training", Status: "completed", FY: "2027", SchoolID: "s1"}
	with := func(change func(*followedSession)) followedSession {
		next := training
		change(&next)
		return next
	}
	tests := []struct {
		name   string
		source followedSession
		want   string
	}{
		{"a completed training here", training, ""},
		{"awaiting verification still counts", with(func(a *followedSession) { a.Status = "submitted_to_pl" }), ""},
		{"a donor visit", with(func(a *followedSession) { a.Type = "donor_visit" }), wrongKind},
		{"a training not delivered", with(func(a *followedSession) { a.Status = "scheduled" }), notDone},
		{"last year's training", with(func(a *followedSession) { a.FY = "2026" }), otherYear},
		{"a training at another school", with(func(a *followedSession) { a.SchoolID = "s2" }), otherPlace},
		{"a cluster session it missed", with(func(a *followedSession) { a.Type, a.SchoolID = "cluster_training", "" }), notThere},
		{"a cluster session it attended", with(func(a *followedSession) {
			a.Type, a.SchoolID, a.Attended = "cluster_meeting", "", true
		}), ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := tt.source.problem("s1", "2027"); got != tt.want {
				t.Fatalf("problem = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestAFollowUpInheritsTheSessionsIntervention(t *testing.T) {
	if got := (followedSession{Focus: "leadership", PurposeFocus: "enrolment"}).inherited(); got != "leadership" {
		t.Fatalf("focus first: %q", got)
	}
	if got := (followedSession{PurposeFocus: "enrolment"}).inherited(); got != "enrolment" {
		t.Fatalf("purpose next: %q", got)
	}
}

func TestAFollowUpCarriesTheSessionsRecommendationSource(t *testing.T) {
	source := followedSession{ID: "a1", Recommendation: map[string]any{"trainingCourseId": "c1", "engine": "old"}}
	got := source.inheritInto(map[string]any{"engine": "standard_support"})
	want := map[string]any{"trainingCourseId": "c1", "engine": "standard_support", "inheritedFromActivityId": "a1"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if source.Recommendation["engine"] != "old" {
		t.Fatal("the session's own source must not change")
	}
}

func TestAFollowUpSourceIsReadFromTheForm(t *testing.T) {
	req, taken := RequestFromForm(map[string][]string{
		"require_catalogue": {"yes"}, "purpose_of_visit": {"training_follow_up"}, "source_activity_id": {" a1 "},
	})
	if !taken || req.SourceActivityID != "a1" {
		t.Fatalf("taken = %v, source = %q", taken, req.SourceActivityID)
	}
}
