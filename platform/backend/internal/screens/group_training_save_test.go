package screens

import (
	"context"
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// docs/migration/38: a cluster's Group Training is Go's only behind its
// own switch, and a form Go does not take, or hands on, is never made here.

type fakeGroupSaver struct {
	answer activities.Answer
	err    error
	got    []activities.GroupTrainingRequest
}

func (f *fakeGroupSaver) ScheduleGroupTraining(_ context.Context, _ auth.Principal, req activities.GroupTrainingRequest,
	_ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, req)
	return f.answer, f.err
}

func clusterForm(facilitator string) url.Values {
	return url.Values{
		"cluster_id": {"c1"}, "activity_type": {"cluster_training"}, "invited_schools_shown": {"1"},
		"invited_school_ids": {"s1", "s2"}, "facilitating_partner_id": {facilitator}, "teachers_per_school": {"2"},
		"catalogue_item_id": {"course"}, "scheduled_date": {"2026-11-26"},
	}
}

func TestTheGroupTrainingIsGoOnlyWithItsSwitch(t *testing.T) {
	words := "Cluster activity scheduled. It is on your My Plan — keep planning."
	tests := []struct {
		name     string
		on       bool
		form     url.Values
		err      error
		wantGo   bool
		wantSave bool
	}{
		{name: "the switch off", form: clusterForm("")},
		{name: "the switch on", on: true, form: clusterForm(""), wantGo: true, wantSave: true},
		{name: "a partner facilitating", on: true, form: clusterForm("p1")},
		{name: "a refusal is answered in the existing words", on: true, form: clusterForm(""),
			err: &activities.Refusal{Message: "Tick the schools this training is for."}, wantGo: true},
		{name: "a hand-on is forwarded", on: true, form: clusterForm(""), err: activities.ErrHandOn},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			saver := &fakeGroupSaver{answer: activities.Answer{Message: words}, err: test.err}
			service := NewService(&formFetcher{})
			if test.on {
				service.WithGroupTrainingSave(saver, nil)
			}

			answer, served, err := service.ScheduleGroupTrainingInGo(signedIn(), test.form, activities.Origin{})

			if err != nil {
				t.Fatal(err)
			}
			if served != test.wantGo {
				t.Fatalf("served %v, want %v", served, test.wantGo)
			}
			if test.wantSave && (!answer.GetSaved() || answer.GetMessage() != words) {
				t.Fatalf("answer %v", answer)
			}
			if test.err != nil && test.wantGo && answer.GetError() != "Tick the schools this training is for." {
				t.Fatalf("refusal %v", answer)
			}
		})
	}
}
