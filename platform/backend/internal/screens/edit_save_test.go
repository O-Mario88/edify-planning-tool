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

type fakeEditor struct {
	answer activities.EditAnswer
	err    error
	got    []activities.EditRequest
	origin activities.Origin
}

func (f *fakeEditor) Edit(_ context.Context, _ auth.Principal, req activities.EditRequest, origin activities.Origin) (activities.EditAnswer, error) {
	f.got, f.origin = append(f.got, req), origin
	return f.answer, f.err
}

const editForm = `{"form": {"csrfmiddlewaretoken": "t", "scheduled_date": "2026-11-17", "purpose_type": "donor_visit",
  "school_id": "1650", "focus_intervention": "", "activity_purpose_text": " New goal ", "expected_outcome": "Outcome"},
 "save": "/my-plan/act1/edit",
 "origin": {"ip": "127.0.0.1", "agent": "Go-http-client/1.1", "correlation": "c1"}}`

func saveEdit(t *testing.T, service *Service, path string) (*screensv1.SaveDrawerResponse, error) {
	t.Helper()
	answer, err := service.SaveDrawer(signedIn(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: path, Values: map[string]string{"activity_purpose_text": "New goal"},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestTheEditIsForwardedWhileTheSwitchIsOff(t *testing.T) {
	fetcher := &moveFetcher{form: editForm}

	answer, err := saveEdit(t, NewService(fetcher), "/my-plan/act1/edit-drawer")

	if err != nil || answer.GetMessage() != "forwarded" {
		t.Fatalf("got %v, %v", answer, err)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/drawer]" {
		t.Fatalf("asked %v", fetcher.paths)
	}
}

func TestGoMakesTheEditItTakesAndForwardsNothing(t *testing.T) {
	fetcher := &moveFetcher{form: editForm}
	editor := &fakeEditor{answer: activities.EditAnswer{Message: "Saved. Press Refresh to see it on the page."}}

	answer, err := saveEdit(t, NewService(fetcher).WithEditSave(editor, nil), "/my-plan/act1/edit-drawer")

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
	if len(editor.got) != 1 || editor.got[0].ActivityID != "act1" ||
		editor.got[0].Posted["activity_purpose_text"] != "New goal" || len(editor.got[0].Posted) != 6 {
		t.Fatalf("request %+v", editor.got)
	}
	if editor.origin.CorrelationID != "c1" {
		t.Fatalf("origin %+v", editor.origin)
	}
}

func TestTheEditIsForwardedWhenGoDoesNotTakeIt(t *testing.T) {
	cases := map[string]struct {
		path, form string
		err        error
	}{
		"handed on":          {"/my-plan/act1/edit-drawer", editForm, activities.ErrHandOn},
		"another drawer":     {"/my-plan/act1/cancel-drawer", editForm, nil},
		"a save elsewhere":   {"/my-plan/act1/edit-drawer", `{"form": {}, "save": "/my-plan/act2/edit", "origin": {}}`, nil},
		"a form not of text": {"/my-plan/act1/edit-drawer", `{"form": {"invited_school_ids": ["a"]}, "save": "/my-plan/act1/edit"}`, nil},
		"a project field":    {"/my-plan/act1/edit-drawer", `{"form": {"project_id": "p"}, "save": "/my-plan/act1/edit"}`, nil},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			fetcher := &moveFetcher{form: c.form}
			editor := &fakeEditor{err: c.err}
			answer, err := saveEdit(t, NewService(fetcher).WithEditSave(editor, nil), c.path)
			if err != nil || answer.GetMessage() != "forwarded" {
				t.Fatalf("got %v, %v", answer, err)
			}
		})
	}
}

// error_fragment(exc, action="Activity not saved"): the action, then the words.
func TestTheEditsRefusalAndFailureAnswerAsTheFeedDoes(t *testing.T) {
	refused := &fakeEditor{err: &activities.Refusal{Message: "Give the reason the date is changing."}}
	answer, err := saveEdit(t, NewService(&moveFetcher{form: editForm}).WithEditSave(refused, nil), "/my-plan/act1/edit-drawer")
	want := &screensv1.SaveDrawerResponse{Error: "Activity not saved: Give the reason the date is changing."}
	if err != nil || !proto.Equal(answer, want) {
		t.Fatalf("refusal: %v, %v", answer, err)
	}
	failed := &fakeEditor{err: errors.New("database down")}
	_, err = saveEdit(t, NewService(&moveFetcher{form: editForm}).WithEditSave(failed, nil), "/my-plan/act1/edit-drawer")
	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("failure: %v", err)
	}
}
