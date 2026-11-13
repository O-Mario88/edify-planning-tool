package screens

import (
	"context"
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// docs/migration/49: a cluster meeting is Go's only behind its own switch,
// and a form Go does not take, or hands on, is never made here.

type fakeMeetingSaver struct {
	answer activities.Answer
	err    error
	got    []activities.ClusterMeetingRequest
}

func (f *fakeMeetingSaver) ScheduleClusterMeeting(_ context.Context, _ auth.Principal, req activities.ClusterMeetingRequest,
	_ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, req)
	return f.answer, f.err
}

func meetingForm(kind, facilitator string) url.Values {
	return url.Values{
		"cluster_id": {"c1"}, "activity_type": {"cluster_meeting"}, "invited_schools_shown": {"1"},
		"invited_school_ids": {"s1", "s2"}, "facilitating_partner_id": {facilitator}, "leaders_per_school": {"2"},
		"purpose_type": {"operational_admin"}, "meeting_kind": {kind}, "scheduled_date": {"2026-11-26"},
	}
}

func TestTheClusterMeetingIsGoOnlyWithItsSwitch(t *testing.T) {
	words := "Cluster activity scheduled. It is on your My Plan — keep planning."
	refusal := "Choose the meeting type: Training, Only Meeting or Cluster Leaders Meeting."
	tests := []struct {
		name     string
		on       bool
		form     url.Values
		err      error
		wantGo   bool
		wantSave bool
	}{
		{name: "the switch off", form: meetingForm("only_meeting", "")},
		{name: "the switch on", on: true, form: meetingForm("only_meeting", ""), wantGo: true, wantSave: true},
		{name: "a partner facilitating", on: true, form: meetingForm("only_meeting", "p1")},
		{name: "a Group Training's form", on: true, form: clusterForm("")},
		{name: "a refusal is answered in the existing words", on: true, form: meetingForm("workshop", ""),
			err: &activities.Refusal{Message: refusal}, wantGo: true},
		{name: "a hand-on is forwarded", on: true, form: meetingForm("training", ""), err: activities.ErrHandOn},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			saver := &fakeMeetingSaver{answer: activities.Answer{Message: words}, err: test.err}
			service := NewService(&formFetcher{})
			if test.on {
				service.WithClusterMeetingSave(saver, nil)
			}

			answer, served, err := service.ScheduleClusterMeetingInGo(signedIn(), test.form, activities.Origin{})

			if err != nil {
				t.Fatal(err)
			}
			if served != test.wantGo {
				t.Fatalf("served %v, want %v", served, test.wantGo)
			}
			if test.wantSave && (!answer.GetSaved() || answer.GetMessage() != words) {
				t.Fatalf("answer %v", answer)
			}
			if test.err != nil && test.wantGo && answer.GetError() != refusal {
				t.Fatalf("refusal %v", answer)
			}
		})
	}
}
