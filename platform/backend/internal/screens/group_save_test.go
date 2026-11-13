package screens

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

type fakeGroup struct {
	answer activities.GroupAnswer
	err    error
	got    []activities.GroupRequest
	kinds  []string
	origin activities.Origin
}

func (f *fakeGroup) GroupReschedule(_ context.Context, _ auth.Principal, req activities.GroupRequest, origin activities.Origin) (activities.GroupAnswer, error) {
	f.got, f.kinds, f.origin = append(f.got, req), append(f.kinds, "reschedule"), origin
	return f.answer, f.err
}

func (f *fakeGroup) GroupCancel(_ context.Context, _ auth.Principal, req activities.GroupRequest, origin activities.Origin) (activities.GroupAnswer, error) {
	f.got, f.kinds, f.origin = append(f.got, req), append(f.kinds, "cancel"), origin
	return f.answer, f.err
}

const (
	groupMoveForm = `{"form": {"activity_ids": ["act1", "act2"], "scheduled_date": "2026-11-19",
  "reason": "the school asked", "csrfmiddlewaretoken": "t"},
 "save": "/activity-selection/reschedule",
 "origin": {"ip": "127.0.0.1", "agent": "Go-http-client/1.1", "correlation": "c1"}}`
	groupCancelForm = `{"form": {"activity_ids": "act1", "reason": "exams"},
 "save": "/activity-selection/cancel", "origin": {"correlation": "c2"}}`
	groupMoveDrawer   = "/activity-selection/reschedule?ids=act1,act2"
	groupCancelDrawer = "/activity-selection/cancel?ids=act1"
)

func saveGroup(t *testing.T, service *Service, path string) (*screensv1.SaveDrawerResponse, error) {
	t.Helper()
	answer, err := service.SaveDrawer(signedIn(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: path, Values: map[string]string{"scheduled_date": "2026-11-19", "reason": "the school asked"},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestTheGroupIsForwardedWhileItsSwitchIsOff(t *testing.T) {
	for _, path := range []string{groupMoveDrawer, groupCancelPath} {
		fetcher := &moveFetcher{form: groupMoveForm}
		// The other group's switch is on: each switch moves only its own.
		service := NewService(fetcher)
		if path == groupMoveDrawer {
			service.WithGroupCancelSave(&fakeGroup{}, nil)
		} else {
			service.WithGroupMoveSave(&fakeGroup{}, nil)
		}
		answer, err := saveGroup(t, service, path)
		if err != nil || answer.GetMessage() != "forwarded" {
			t.Fatalf("%s: got %v, %v", path, answer, err)
		}
		if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/drawer]" {
			t.Fatalf("%s: asked %v", path, fetcher.paths)
		}
	}
}

func TestGoMakesTheGroupItTakesWithEveryTickAndForwardsNothing(t *testing.T) {
	fetcher := &moveFetcher{form: groupMoveForm}
	group := &fakeGroup{answer: activities.GroupAnswer{
		Done: []activities.GroupPick{{ActivityID: "act1"}, {ActivityID: "act2"}}, Message: "2 activities moved to 19 November 2026.",
	}}

	answer, err := saveGroup(t, NewService(fetcher).WithGroupMoveSave(group, nil), groupMoveDrawer)

	if err != nil {
		t.Fatal(err)
	}
	// _saved_outcome joins the flash messages as they are: no toast button.
	want := &screensv1.SaveDrawerResponse{Saved: true, Message: "2 activities moved to 19 November 2026."}
	if !proto.Equal(answer, want) {
		t.Fatalf("answer %v, want %v", answer, want)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/drawer?form_only=1]" {
		t.Fatalf("asked %v (the group must not be forwarded too)", fetcher.paths)
	}
	got := group.got[0]
	if !slices.Equal(got.ActivityIDs, []string{"act1", "act2"}) || got.Date != "2026-11-19" || got.Reason != "the school asked" {
		t.Fatalf("request %+v", got)
	}
	if group.origin.CorrelationID != "c1" || group.kinds[0] != "reschedule" {
		t.Fatalf("origin %+v, kind %v", group.origin, group.kinds)
	}
}

// One ticked activity comes back from the feed as one text, not a list.
func TestTheGroupCancelTakesOneTickAsText(t *testing.T) {
	group := &fakeGroup{answer: activities.GroupAnswer{Done: []activities.GroupPick{{ActivityID: "act1"}}, Message: "1 activity cancelled."}}

	answer, err := saveGroup(t, NewService(&moveFetcher{form: groupCancelForm}).WithGroupCancelSave(group, nil), groupCancelPath)

	if err != nil || !answer.GetSaved() || answer.GetMessage() != "1 activity cancelled." {
		t.Fatalf("got %v, %v", answer, err)
	}
	if !slices.Equal(group.got[0].ActivityIDs, []string{"act1"}) || group.kinds[0] != "cancel" {
		t.Fatalf("request %+v %v", group.got, group.kinds)
	}
}

func TestTheGroupIsForwardedWholeWhenGoDoesNotTakeIt(t *testing.T) {
	cases := map[string]struct {
		path, form string
		err        error
	}{
		"a ticked activity handed on": {groupMoveDrawer, groupMoveForm, activities.ErrHandOn},
		"a save elsewhere":            {groupMoveDrawer, `{"form": {}, "save": "/activity-selection/cancel", "origin": {}}`, nil},
		"a form not of text":          {groupMoveDrawer, `{"form": {"activity_ids": [1]}, "save": "/activity-selection/reschedule"}`, nil},
		"another bar's drawer":        {"/planning/bulk-schedule?school_ids=s1", groupMoveForm, nil},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			fetcher := &moveFetcher{form: c.form}
			group := &fakeGroup{err: c.err}
			answer, err := saveGroup(t, NewService(fetcher).WithGroupMoveSave(group, nil).WithGroupCancelSave(group, nil), c.path)
			if err != nil || answer.GetMessage() != "forwarded" {
				t.Fatalf("got %v, %v", answer, err)
			}
		})
	}
}

// error_fragment's words for a refusal of the group (the cancel's with its
// action), the outcome partial's words when nothing changed, and a failure
// before the group as Unavailable with nothing forwarded.
func TestTheGroupsRefusalsAnswerAsTheFeedDoes(t *testing.T) {
	cases := []struct {
		path, form string
		group      *fakeGroup
		want       *screensv1.SaveDrawerResponse
	}{
		{groupMoveDrawer, groupMoveForm, &fakeGroup{err: &activities.Refusal{Message: "Give the reason these activities are moving."}},
			&screensv1.SaveDrawerResponse{Error: "Give the reason these activities are moving."}},
		{groupCancelPath, groupCancelForm, &fakeGroup{err: &activities.Refusal{Message: "Give the reason these activities are being cancelled."}},
			&screensv1.SaveDrawerResponse{Error: "Cancellation Error: Give the reason these activities are being cancelled."}},
		{groupMoveDrawer, groupMoveForm, &fakeGroup{answer: activities.GroupAnswer{
			Refused: []activities.GroupPick{{ActivityID: "act1"}},
			Outcome: "Nothing was moved. Donor Visit · Kasawo  Primary: 10 November 2026 has passed."}},
			&screensv1.SaveDrawerResponse{Error: "Nothing was moved. Donor Visit · Kasawo Primary: 10 November 2026 has passed."}},
	}
	for _, c := range cases {
		service := NewService(&moveFetcher{form: c.form}).WithGroupMoveSave(c.group, nil).WithGroupCancelSave(c.group, nil)
		answer, err := saveGroup(t, service, c.path)
		if err != nil || !proto.Equal(answer, c.want) {
			t.Errorf("%s: %v, %v; want %v", c.path, answer, err, c.want)
		}
	}
	fetcher := &moveFetcher{form: groupMoveForm}
	_, err := saveGroup(t, NewService(fetcher).WithGroupMoveSave(&fakeGroup{err: errors.New("database down")}, nil), groupMoveDrawer)
	if connect.CodeOf(err) != connect.CodeUnavailable || len(fetcher.paths) != 1 {
		t.Fatalf("failure: %v, asked %v", err, fetcher.paths)
	}
}
