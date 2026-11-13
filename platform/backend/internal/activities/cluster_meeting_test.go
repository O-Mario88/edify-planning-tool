package activities

import (
	"errors"
	"net/url"
	"testing"
)

// docs/migration/49: the cluster meeting's rules that the seed cannot
// reach, and the ones it can, before any read.

func meetingForm() url.Values {
	f := groupForm()
	f.Del("catalogue_item_id")
	f.Set("activity_type", "cluster_meeting")
	f.Set("purpose_type", "operational_admin")
	f.Set("meeting_kind", "only_meeting")
	f.Set("focus_intervention", "")
	return f
}

func TestTheMeetingFormIsTakenOnlyForTheOwnersStaffMeeting(t *testing.T) {
	f := meetingForm()
	f.Set("focus_intervention", "leadership")
	req, ok := ClusterMeetingRequestFromForm(f)
	if !ok || req.ClusterID != "c1" || len(req.Invited) != 2 || !req.InvitedShown || req.MeetingKind != "only_meeting" ||
		req.Focus != "leadership" || req.PurposeType != "operational_admin" || req.Leaders != "1" {
		t.Fatalf("the drawer's own form: %v %+v", ok, req)
	}
	handedOn := map[string]func(url.Values){
		"a partner facilitates":       func(f url.Values) { f.Set("facilitating_partner_id", "p1") },
		"no Facilitated by field":     func(f url.Values) { f.Del("facilitating_partner_id") },
		"a Training meeting's course": func(f url.Values) { f.Set("training_course_id", "course") },
		"a catalogue item posted":     func(f url.Values) { f.Set("catalogue_item_id", "item") },
		"a responsible person named":  func(f url.Values) { f.Set("responsible_staff_id", "x") },
		"a priority":                  func(f url.Values) { f.Set("priority_allocation_id", "p") },
		"partner delivery":            func(f url.Values) { f.Set("delivery_type", "partner") },
		"a group training":            func(f url.Values) { f.Set("activity_type", "cluster_training") },
		"a school":                    func(f url.Values) { f.Set("school_id", "S-1") },
	}
	for name, change := range handedOn {
		f := meetingForm()
		change(f)
		if _, ok := ClusterMeetingRequestFromForm(f); ok {
			t.Errorf("%s: must be handed on", name)
		}
	}
	if _, ok := GroupTrainingRequestFromForm(meetingForm()); ok {
		t.Error("a meeting is not a Group Training")
	}
}

func TestTheMeetingKindAndFocusAreReadAsTheViewReadsThem(t *testing.T) {
	tests := []struct {
		name, kind, focus, purpose string
		refusal                    string
		handOn                     bool
	}{
		{name: "only a meeting", kind: "only_meeting", purpose: "operational_admin"},
		{name: "a leaders' meeting with a focus", kind: "cluster_leaders", focus: "leadership", purpose: "operational_admin"},
		{name: "an unknown type", kind: "workshop", purpose: "operational_admin", refusal: unknownMeetingKind},
		{name: "a Training meeting (a course and a ceiling)", kind: "training", purpose: "operational_admin", handOn: true},
		{name: "no type (a caller that never asked)", purpose: "operational_admin", handOn: true},
		{name: "a focus that is no SSA intervention", kind: "only_meeting", focus: "budgeting", purpose: "operational_admin", handOn: true},
		{name: "another purpose type", kind: "only_meeting", purpose: "focus_intervention", handOn: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ss, err := meetingSession(ClusterMeetingRequest{MeetingKind: tt.kind, Focus: tt.focus, PurposeType: tt.purpose})
			var refusal *Refusal
			switch {
			case tt.refusal != "":
				if !errors.As(err, &refusal) || refusal.Message != tt.refusal {
					t.Fatalf("want the refusal %q, got %v", tt.refusal, err)
				}
			case tt.handOn:
				if !errors.Is(err, ErrHandOn) {
					t.Fatalf("want a hand-on, got %v", err)
				}
			default:
				if err != nil || ss.activityType != "cluster_meeting" || ss.meetingKind != tt.kind || ss.focus != tt.focus ||
					ss.purpose != "operational_admin" || ss.course != nil {
					t.Fatalf("got %+v, %v", ss, err)
				}
			}
		})
	}
}

func TestAMeetingsFocusIsThePlannersElseTheWeakestNeed(t *testing.T) {
	need := clusterNeed{Priorities: []string{"learning_environment", "leadership"}}
	meeting := session{activityType: "cluster_meeting"}
	any := []string{"any_ssa_intervention"}
	tests := []struct {
		name             string
		ss               session
		modes            []string
		need             clusterNeed
		focus, fromWhere string
	}{
		{name: "named by the planner", ss: session{activityType: "cluster_meeting", focus: "leadership"}, modes: any, need: need,
			focus: "leadership", fromWhere: "planner"},
		{name: "none named: the weakest need", ss: meeting, modes: any, need: need, focus: "learning_environment", fromWhere: "ssa_default"},
		{name: "none named, no assessed school", ss: meeting, modes: any, focus: "", fromWhere: "planner"},
		{name: "an item fixed to no intervention", ss: meeting, modes: []string{"fixed"}, need: need, focus: "", fromWhere: "planner"},
		{name: "an administrative item", ss: meeting, modes: []string{"administrative"}, need: need, focus: "", fromWhere: "planner"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			focus, from, _ := sessionFocus(tt.ss, tt.modes, tt.need)
			if focus != tt.focus || from != tt.fromWhere {
				t.Fatalf("got %q from %q, want %q from %q", focus, from, tt.focus, tt.fromWhere)
			}
		})
	}
}

func TestGoTakesAMeetingsStandardItemAndATrainingsGovernedCourse(t *testing.T) {
	standard := item{WorkflowKind: "cluster_meeting", StandardSupport: true, ParticipantMode: "per_school"}
	meeting := session{activityType: "cluster_meeting"}
	training := session{activityType: "cluster_training", course: &course{ID: "c"}}
	course := item{WorkflowKind: "cluster_training", IsTrainingCourse: true, ParticipantMode: "per_school"}
	tests := []struct {
		name string
		it   item
		ss   session
		want bool
	}{
		{name: "the standard Cluster Meeting", it: standard, ss: meeting, want: true},
		{name: "a governed meeting item", it: item{WorkflowKind: "cluster_meeting", ParticipantMode: "per_school"}, ss: meeting},
		{name: "a meeting item priced per total", it: item{WorkflowKind: "cluster_meeting", StandardSupport: true, ParticipantMode: "none"}, ss: meeting},
		{name: "a meeting item that is a course", it: item{WorkflowKind: "cluster_meeting", StandardSupport: true, IsTrainingCourse: true, ParticipantMode: "per_school"}, ss: meeting},
		{name: "a training's item for a meeting", it: course, ss: meeting},
		{name: "a governed course", it: course, ss: training, want: true},
		{name: "a standard-support course", it: item{WorkflowKind: "cluster_training", StandardSupport: true, IsTrainingCourse: true, ParticipantMode: "per_school"}, ss: training},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := sessionItemTaken(tt.it, tt.ss); got != tt.want {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
		})
	}
}
