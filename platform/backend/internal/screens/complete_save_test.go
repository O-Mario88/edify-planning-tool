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

type fakeCompleter struct {
	answer activities.CompleteAnswer
	err    error
	got    []activities.CompleteRequest
	origin activities.Origin
}

func (f *fakeCompleter) Complete(_ context.Context, _ auth.Principal, req activities.CompleteRequest, origin activities.Origin) (activities.CompleteAnswer, error) {
	f.got, f.origin = append(f.got, req), origin
	return f.answer, f.err
}

const completeForm = `{"form": {"salesforce_id": "SV-990001", "actual_delivery_date": "2026-11-20"},
 "save": "/my-plan/act1/complete",
 "origin": {"ip": "127.0.0.1", "agent": "Go-http-client/1.1", "correlation": "c1"}}`

func saveComplete(t *testing.T, service *Service, path string) (*screensv1.SaveDrawerResponse, error) {
	t.Helper()
	answer, err := service.SaveDrawer(signedIn(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: path, Values: map[string]string{"salesforce_id": "SV-990001"},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestTheCompletionIsForwardedWhileTheSwitchIsOff(t *testing.T) {
	fetcher := &moveFetcher{form: completeForm}

	answer, err := saveComplete(t, NewService(fetcher), "/my-plan/act1/complete-drawer")

	if err != nil || answer.GetMessage() != "forwarded" {
		t.Fatalf("got %v, %v", answer, err)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/drawer]" {
		t.Fatalf("asked %v", fetcher.paths)
	}
}

func TestGoMakesTheCompletionItTakesAndForwardsNothing(t *testing.T) {
	fetcher := &moveFetcher{form: completeForm}
	completer := &fakeCompleter{answer: activities.CompleteAnswer{Message: "Saved. Press Refresh to see it on the page."}}

	answer, err := saveComplete(t, NewService(fetcher).WithCompleteSave(completer, nil), "/my-plan/act1/complete-drawer")

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
	if len(completer.got) != 1 || completer.got[0].ActivityID != "act1" || completer.got[0].Form.Get("salesforce_id") != "SV-990001" {
		t.Fatalf("request %+v", completer.got)
	}
	if completer.origin.CorrelationID != "c1" {
		t.Fatalf("origin %+v", completer.origin)
	}
}

func TestTheCompletionIsForwardedWhenGoDoesNotTakeIt(t *testing.T) {
	cases := map[string]struct {
		path, form string
		err        error
	}{
		"handed on":          {"/my-plan/act1/complete-drawer", completeForm, activities.ErrHandOn},
		"another drawer":     {"/my-plan/act1/cancel-drawer", completeForm, nil},
		"a save elsewhere":   {"/my-plan/act1/complete-drawer", `{"form": {}, "save": "/my-plan/act2/complete", "origin": {}}`, nil},
		"a form not of text": {"/my-plan/act1/complete-drawer", `{"form": {"attended_school_ids": ["s1"]}, "save": "/my-plan/act1/complete"}`, nil},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			fetcher := &moveFetcher{form: c.form}
			completer := &fakeCompleter{err: c.err}
			answer, err := saveComplete(t, NewService(fetcher).WithCompleteSave(completer, nil), c.path)
			if err != nil || answer.GetMessage() != "forwarded" {
				t.Fatalf("got %v, %v", answer, err)
			}
		})
	}
}

// error_fragment(exc, action="Submission Error"): the action, then the words.
func TestTheCompletionsRefusalAndFailureAnswerAsTheFeedDoes(t *testing.T) {
	refused := &fakeCompleter{err: &activities.Refusal{Message: "Enter the Salesforce ID as SV-… or SVE-…, or the record's own Salesforce ID."}}
	answer, err := saveComplete(t, NewService(&moveFetcher{form: completeForm}).WithCompleteSave(refused, nil), "/my-plan/act1/complete-drawer")
	want := &screensv1.SaveDrawerResponse{Error: "Submission Error: Enter the Salesforce ID as SV-… or SVE-…, or the record's own Salesforce ID."}
	if err != nil || !proto.Equal(answer, want) {
		t.Fatalf("refusal: %v, %v", answer, err)
	}
	failed := &fakeCompleter{err: errors.New("database down")}
	_, err = saveComplete(t, NewService(&moveFetcher{form: completeForm}).WithCompleteSave(failed, nil), "/my-plan/act1/complete-drawer")
	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("failure: %v", err)
	}
}
