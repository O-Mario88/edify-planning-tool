package screens

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

type fakeCanceller struct {
	answer activities.CancelAnswer
	err    error
	got    []activities.CancelRequest
	origin activities.Origin
}

func (f *fakeCanceller) Cancel(_ context.Context, _ auth.Principal, req activities.CancelRequest, origin activities.Origin) (activities.CancelAnswer, error) {
	f.got, f.origin = append(f.got, req), origin
	return f.answer, f.err
}

const cancelForm = `{"form": {"reason": "the school closed", "csrfmiddlewaretoken": "t"},
 "save": "/my-plan/act1/cancel",
 "origin": {"ip": "127.0.0.1", "agent": "Go-http-client/1.1", "correlation": "c1"}}`

func saveCancel(t *testing.T, service *Service, path string) (*screensv1.SaveDrawerResponse, error) {
	t.Helper()
	answer, err := service.SaveDrawer(signedIn(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: path, Values: map[string]string{"reason": "the school closed"},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestTheCancelIsForwardedWhileTheSwitchIsOff(t *testing.T) {
	fetcher := &moveFetcher{form: cancelForm}

	answer, err := saveCancel(t, NewService(fetcher), "/my-plan/act1/cancel-drawer")

	if err != nil || answer.GetMessage() != "forwarded" {
		t.Fatalf("got %v, %v", answer, err)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/drawer]" {
		t.Fatalf("asked %v", fetcher.paths)
	}
}

func TestGoMakesTheCancelItTakesAndForwardsNothing(t *testing.T) {
	fetcher := &moveFetcher{form: cancelForm}
	canceller := &fakeCanceller{answer: activities.CancelAnswer{Message: "Saved. Press Refresh to see it on the page."}}

	answer, err := saveCancel(t, NewService(fetcher).WithCancelSave(canceller, nil), "/my-plan/act1/cancel-drawer")

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
	if len(canceller.got) != 1 || canceller.got[0] != (activities.CancelRequest{ActivityID: "act1", Reason: "the school closed"}) {
		t.Fatalf("request %+v", canceller.got)
	}
	if canceller.origin.CorrelationID != "c1" {
		t.Fatalf("origin %+v", canceller.origin)
	}
}

func TestTheCancelIsForwardedWhenGoDoesNotTakeIt(t *testing.T) {
	cases := map[string]struct {
		path, form string
		err        error
	}{
		"handed on":          {"/my-plan/act1/cancel-drawer", cancelForm, activities.ErrHandOn},
		"another drawer":     {"/my-plan/act1/complete-drawer", cancelForm, nil},
		"a save elsewhere":   {"/my-plan/act1/cancel-drawer", `{"form": {}, "save": "/my-plan/act2/cancel", "origin": {}}`, nil},
		"a form not of text": {"/my-plan/act1/cancel-drawer", `{"form": {"x": 1}, "save": "/my-plan/act1/cancel"}`, nil},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			fetcher := &moveFetcher{form: c.form}
			canceller := &fakeCanceller{err: c.err}
			answer, err := saveCancel(t, NewService(fetcher).WithCancelSave(canceller, nil), c.path)
			if err != nil || answer.GetMessage() != "forwarded" {
				t.Fatalf("got %v, %v", answer, err)
			}
		})
	}
}

// error_fragment(exc, action="Cancellation Error"): the action, then the words.
func TestTheCancelsRefusalAndFailureAnswerAsTheFeedDoes(t *testing.T) {
	refused := &fakeCanceller{err: &activities.Refusal{Message: "Give a reason this activity is being cancelled."}}
	answer, err := saveCancel(t, NewService(&moveFetcher{form: cancelForm}).WithCancelSave(refused, nil), "/my-plan/act1/cancel-drawer")
	want := &screensv1.SaveDrawerResponse{Error: "Cancellation Error: Give a reason this activity is being cancelled."}
	if err != nil || !proto.Equal(answer, want) {
		t.Fatalf("refusal: %v, %v", answer, err)
	}
	failed := &fakeCanceller{err: errors.New("database down")}
	_, err = saveCancel(t, NewService(&moveFetcher{form: cancelForm}).WithCancelSave(failed, nil), "/my-plan/act1/cancel-drawer")
	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("failure: %v", err)
	}
}
