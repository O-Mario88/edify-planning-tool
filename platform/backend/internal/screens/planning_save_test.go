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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// formFetcher answers the form-only request with form, and records every
// call; the forwarded save answers forwarded.
type formFetcher struct {
	paths   []string
	form    string // the form-only answer's JSON
	formErr error
}

func (f *formFetcher) Get(_ context.Context, path string, _ proto.Message) error {
	f.paths = append(f.paths, path)
	return nil
}

func (f *formFetcher) Post(_ context.Context, path string, _, out proto.Message) error {
	f.paths = append(f.paths, "POST "+path)
	if path == "/api/mobile/v1/schools/s1/planning/schedule?form_only=1" {
		if f.formErr != nil {
			return f.formErr
		}
		return protojson.Unmarshal([]byte(f.form), out)
	}
	return protojson.Unmarshal([]byte(`{"saved": true, "message": "forwarded"}`), out)
}

type fakeSaver struct {
	answer activities.Answer
	err    error
	got    []activities.Request
	origin activities.Origin
}

func (f *fakeSaver) Schedule(_ context.Context, _ auth.Principal, req activities.Request, origin activities.Origin) (activities.Answer, error) {
	f.got, f.origin = append(f.got, req), origin
	return f.answer, f.err
}

const visitForm = `{"form": {"school_id": "FEED-1", "purpose_of_visit": "donor_visit",
 "scheduled_date": "2026-11-20", "require_catalogue": "yes", "delivery_type": "staff",
 "executor_type": "staff", "activity_purpose_text": "a goal", "csrfmiddlewaretoken": "t"},
 "origin": {"ip": "127.0.0.1", "agent": "Go-http-client/1.1", "correlation": "c1"}}`

func saveSchedule(t *testing.T, service *Service, ctx context.Context) (*screensv1.SavePlanningDrawerResponse, error) {
	t.Helper()
	answer, err := service.SavePlanningDrawer(ctx, connect.NewRequest(&screensv1.SavePlanningDrawerRequest{
		SchoolId: "s1", Kind: "schedule", Values: map[string]string{"purpose_of_visit": "donor_visit"},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func signedIn() context.Context {
	return auth.WithPrincipal(context.Background(), auth.Principal{})
}

func TestTheScheduleSaveIsForwardedWhileTheSwitchIsOff(t *testing.T) {
	fetcher := &formFetcher{form: visitForm}

	answer, err := saveSchedule(t, NewService(fetcher), signedIn())

	if err != nil || answer.GetMessage() != "forwarded" {
		t.Fatalf("got %v, %v", answer, err)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/schools/s1/planning/schedule]" {
		t.Fatalf("asked %v", fetcher.paths)
	}
}

func TestGoMakesTheSaveItTakesWithTheFormsOwnFieldsAndOrigin(t *testing.T) {
	fetcher := &formFetcher{form: visitForm}
	saver := &fakeSaver{answer: activities.Answer{Message: "School visit scheduled. It is on your My Plan — keep planning."}}
	service := NewService(fetcher).WithVisitSave(saver, nil)

	answer, err := saveSchedule(t, service, signedIn())

	if err != nil {
		t.Fatal(err)
	}
	want := &screensv1.SavePlanningDrawerResponse{Saved: true, Message: "School visit scheduled. It is on your My Plan — keep planning."}
	if !proto.Equal(answer, want) {
		t.Fatalf("answer %v, want %v", answer, want)
	}
	if fmt.Sprint(fetcher.paths) != "[POST /api/mobile/v1/schools/s1/planning/schedule?form_only=1]" {
		t.Fatalf("asked %v (the save must not be forwarded too)", fetcher.paths)
	}
	if len(saver.got) != 1 || saver.got[0].SchoolID != "FEED-1" || saver.got[0].Goal != "a goal" {
		t.Fatalf("request %+v", saver.got)
	}
	if saver.origin != (activities.Origin{IP: "127.0.0.1", UserAgent: "Go-http-client/1.1", CorrelationID: "c1"}) {
		t.Fatalf("origin %+v", saver.origin)
	}
}

func TestWhatGoDoesNotTakeIsForwardedUnchanged(t *testing.T) {
	partnerForm := `{"form": {"school_id": "FEED-1", "require_catalogue": "yes", "facilitating_partner_id": "p1"}}`
	tests := []struct {
		name  string
		form  string
		err   error
		ctx   context.Context
		asked bool // whether Go was asked at all
	}{
		{name: "Go hands it on", form: visitForm, err: fmt.Errorf("%w: a Core school", activities.ErrHandOn), ctx: signedIn(), asked: true},
		{name: "a field outside the case", form: partnerForm, ctx: signedIn()},
		{name: "a form in another shape", form: `{"saved": false, "error": "x"}`, ctx: signedIn()},
		{name: "a value that is not text", form: `{"form": {"school_id": 3}}`, ctx: signedIn()},
		{name: "someone in an acting seat", form: visitForm, ctx: auth.WithPrincipal(context.Background(),
			auth.Principal{Account: auth.Account{InActingAppointment: true}})},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fetcher := &formFetcher{form: test.form}
			saver := &fakeSaver{err: test.err}

			answer, err := saveSchedule(t, NewService(fetcher).WithVisitSave(saver, nil), test.ctx)

			if err != nil || answer.GetMessage() != "forwarded" {
				t.Fatalf("got %v, %v", answer, err)
			}
			if last := fetcher.paths[len(fetcher.paths)-1]; last != "POST /api/mobile/v1/schools/s1/planning/schedule" {
				t.Fatalf("last call %q", last)
			}
			if (len(saver.got) == 1) != test.asked {
				t.Fatalf("Go asked %d times", len(saver.got))
			}
		})
	}
}

func TestTheAnswerIsInTheExistingFeedsWords(t *testing.T) {
	tests := []struct {
		name   string
		answer activities.Answer
		err    error
		want   *screensv1.SavePlanningDrawerResponse
	}{
		{
			name:   "saved with the ceiling notice under it",
			answer: activities.Answer{Message: "School visit scheduled.", Notice: "  You are past\n 280 visits. "},
			want:   &screensv1.SavePlanningDrawerResponse{Saved: true, Message: "School visit scheduled. You are past 280 visits."},
		},
		{
			name:   "saved without a notice",
			answer: activities.Answer{Message: "School visit scheduled.", Notice: " \n"},
			want:   &screensv1.SavePlanningDrawerResponse{Saved: true, Message: "School visit scheduled."},
		},
		{
			name: "refused",
			err:  &activities.Refusal{Message: "10 November 2026 has passed. Schedule work from 12 November 2026 onwards."},
			want: &screensv1.SavePlanningDrawerResponse{Error: "10 November 2026 has passed. Schedule work from 12 November 2026 onwards."},
		},
		{
			name: "refused at the drawer's gate (the view's 403)",
			err:  &activities.Refusal{Message: "You cannot schedule.", Forbidden: true},
			want: &screensv1.SavePlanningDrawerResponse{Error: "You cannot schedule."},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, served, err := outcomeOf(context.Background(), nil, test.answer, test.err)
			if err != nil || !served || !proto.Equal(got, test.want) {
				t.Fatalf("got %v %v %v, want %v", got, served, err, test.want)
			}
		})
	}
}

func TestAFailedGoSaveSaysItWasNotSaved(t *testing.T) {
	_, served, err := outcomeOf(context.Background(), nil, activities.Answer{}, errors.New("database down"))

	if !served || connect.CodeOf(err) != connect.CodeUnavailable || apierr.Reason(err) != apierr.ReasonInternal {
		t.Fatalf("got %v %v", served, err)
	}
}

func TestTheDrawersOwnRefusalIsTheFormRequestsError(t *testing.T) {
	refused := apierr.New(context.Background(), connect.CodeNotFound, apierr.ReasonNotFound, "This was not found, or it is not yours to view.")
	fetcher := &formFetcher{formErr: refused}
	saver := &fakeSaver{}

	_, err := saveSchedule(t, NewService(fetcher).WithVisitSave(saver, nil), signedIn())

	if !errors.Is(err, refused) && connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("got %v", err)
	}
	if len(saver.got) != 0 || len(fetcher.paths) != 1 {
		t.Fatalf("asked %v, Go %d times", fetcher.paths, len(saver.got))
	}
}

func TestCollapseIsPythonsSplitAndJoin(t *testing.T) {
	for in, want := range map[string]string{
		"":                "",
		"  a \t b\n":      "a b",
		"a b c":           "a b c",
		"a\x1cb\x1fc":     "a b c",
		"keep — the dash": "keep — the dash",
		"x​zero-width":    "x​zero-width", // not whitespace to Python either
	} {
		if got := collapse(in); got != want {
			t.Errorf("collapse(%q) = %q, want %q", in, got, want)
		}
	}
}
