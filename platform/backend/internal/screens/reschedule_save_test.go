package screens

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// moveFetcher answers the drawer feed's form-only request with form; the
// forwarded save answers "forwarded".
type moveFetcher struct {
	paths []string
	form  string
}

func (f *moveFetcher) Get(_ context.Context, path string, _ proto.Message) error {
	f.paths = append(f.paths, path)
	return nil
}

func (f *moveFetcher) Post(_ context.Context, path string, _, out proto.Message) error {
	f.paths = append(f.paths, "POST "+path)
	if path == "/api/mobile/v1/drawer?form_only=1" {
		return protojson.Unmarshal([]byte(f.form), out)
	}
	return protojson.Unmarshal([]byte(`{"saved": true, "message": "forwarded"}`), out)
}

type fakeMover struct {
	answer activities.MoveAnswer
	err    error
	got    []activities.MoveRequest
	origin activities.Origin
}

func (f *fakeMover) Reschedule(_ context.Context, _ auth.Principal, req activities.MoveRequest, origin activities.Origin) (activities.MoveAnswer, error) {
	f.got, f.origin = append(f.got, req), origin
	return f.answer, f.err
}

const moveForm = `{"form": {"scheduled_date": "2026-11-26", "reason": "the school asked", "csrfmiddlewaretoken": "t"},
 "save": "/my-plan/act1/reschedule",
 "origin": {"ip": "127.0.0.1", "agent": "Go-http-client/1.1", "correlation": "c1"}}`

func saveMove(t *testing.T, service *Service, path string) (*screensv1.SaveDrawerResponse, error) {
	t.Helper()
	answer, err := service.SaveDrawer(signedIn(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: path, Values: map[string]string{"scheduled_date": "2026-11-26"},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestTheMoveIsForwardedWhileTheSwitchIsOff(t *testing.T) {
	fetcher := &moveFetcher{form: moveForm}

	answer, err := saveMove(t, NewService(fetcher), "/my-plan/act1/reschedule-drawer")

	if err != nil || answer.GetMessage() != "forwarded" {
		t.Fatalf("got %v, %v", answer, err)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/drawer]" {
		t.Fatalf("asked %v", fetcher.paths)
	}
}

func TestGoMakesTheMoveItTakesAndForwardsNothing(t *testing.T) {
	fetcher := &moveFetcher{form: moveForm}
	mover := &fakeMover{answer: activities.MoveAnswer{Message: "Saved. Press Refresh to see it on the page."}}

	answer, err := saveMove(t, NewService(fetcher).WithMoveSave(mover, nil), "/my-plan/act1/reschedule-drawer")

	if err != nil {
		t.Fatal(err)
	}
	want := &screensv1.SaveDrawerResponse{Saved: true, Message: "Saved. Press Refresh to see it on the page. ×"}
	if !proto.Equal(answer, want) {
		t.Fatalf("answer %v, want %v", answer, want)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/drawer?form_only=1]" {
		t.Fatalf("asked %v (the save must not be forwarded too)", fetcher.paths)
	}
	if len(mover.got) != 1 || mover.got[0] != (activities.MoveRequest{ActivityID: "act1", Date: "2026-11-26", Reason: "the school asked"}) {
		t.Fatalf("request %+v", mover.got)
	}
	if mover.origin.CorrelationID != "c1" {
		t.Fatalf("origin %+v", mover.origin)
	}
}

func TestTheMoveIsForwardedWhenGoDoesNotTakeIt(t *testing.T) {
	cases := map[string]struct {
		path, form string
		err        error
	}{
		"handed on":          {"/my-plan/act1/reschedule-drawer", moveForm, activities.ErrHandOn},
		"another drawer":     {"/my-plan/act1/cancel-drawer", moveForm, nil},
		"a save elsewhere":   {"/my-plan/act1/reschedule-drawer", `{"form": {}, "save": "/my-plan/act2/reschedule", "origin": {}}`, nil},
		"a form not of text": {"/my-plan/act1/reschedule-drawer", `{"form": {"x": 1}, "save": "/my-plan/act1/reschedule"}`, nil},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			fetcher := &moveFetcher{form: c.form}
			mover := &fakeMover{err: c.err}
			answer, err := saveMove(t, NewService(fetcher).WithMoveSave(mover, nil), c.path)
			if err != nil || answer.GetMessage() != "forwarded" {
				t.Fatalf("got %v, %v", answer, err)
			}
		})
	}
}

func TestTheMovesRefusalAndFailureAnswerAsTheFeedDoes(t *testing.T) {
	refused := &fakeMover{err: &activities.Refusal{Message: "Invalid date: "}}
	answer, err := saveMove(t, NewService(&moveFetcher{form: moveForm}).WithMoveSave(refused, nil), "/my-plan/act1/reschedule-drawer")
	if err != nil || !proto.Equal(answer, &screensv1.SaveDrawerResponse{Error: "Invalid date:"}) {
		t.Fatalf("refusal: %v, %v", answer, err)
	}
	failed := &fakeMover{err: errors.New("database down")}
	_, err = saveMove(t, NewService(&moveFetcher{form: moveForm}).WithMoveSave(failed, nil), "/my-plan/act1/reschedule-drawer")
	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("failure: %v", err)
	}
}
