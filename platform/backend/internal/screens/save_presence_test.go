package screens

import (
	"context"
	"errors"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/presence"
)

type fakeStamper struct {
	users []string
	got   []presence.Request
	err   error
}

func (f *fakeStamper) Stamp(_ context.Context, userID string, r presence.Request) (int, error) {
	f.users, f.got = append(f.users, userID), append(f.got, r)
	return 1, f.err
}

func personSaving() context.Context {
	return auth.WithPrincipal(context.Background(), auth.Principal{UserID: "u1"})
}

func saveVisit(service *Service) (*screensv1.SavePlanningDrawerResponse, error) {
	answer, err := service.SavePlanningDrawer(personSaving(), connect.NewRequest(&screensv1.SavePlanningDrawerRequest{
		SchoolId: "s1", Kind: "schedule", Values: map[string]string{
			"purpose_of_visit": "donor_visit", "scheduled_date": "2026-11-20", "delivery_type": "staff",
			"executor_type": "staff", "activity_purpose_text": "a goal",
		},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestASaveWithoutDjangoStampsThePersonOnce(t *testing.T) {
	stamper := &fakeStamper{}
	saver := &fakeSaver{answer: activities.Answer{Message: "Saved."}}
	service := NewService(nil).WithVisitSave(saver, nil).WithPresence(stamper, nil)

	answer, err := saveVisit(service)

	if err != nil || !answer.GetSaved() {
		t.Fatalf("the save should succeed: %v %v", answer, err)
	}
	if len(stamper.got) != 1 || stamper.users[0] != "u1" {
		t.Fatalf("want one stamp for u1, got %v %v", stamper.users, stamper.got)
	}
	want := presence.Request{Method: "POST", Path: "/api/mobile/v1/schools/s1/planning/schedule", Bearer: true}
	if stamper.got[0] != want {
		t.Fatalf("stamp = %+v, want %+v", stamper.got[0], want)
	}
}

func TestARefusedSaveStillStampsThePerson(t *testing.T) {
	stamper := &fakeStamper{}
	saver := &fakeSaver{err: &activities.Refusal{Message: "That date has passed."}}
	service := NewService(nil).WithVisitSave(saver, nil).WithPresence(stamper, nil)

	answer, err := saveVisit(service)

	if err != nil || answer.GetSaved() || answer.GetError() == "" {
		t.Fatalf("the refusal should be answered: %v %v", answer, err)
	}
	if len(stamper.got) != 1 {
		t.Fatalf("want one stamp, got %d", len(stamper.got))
	}
}

func TestASaveThroughDjangoIsNotStampedTwice(t *testing.T) {
	stamper := &fakeStamper{}
	saver := &fakeSaver{answer: activities.Answer{Message: "Saved."}}
	service := NewService(&formFetcher{form: visitForm}).WithVisitSave(saver, nil).WithPresence(stamper, nil)

	if _, err := saveVisit(service); err != nil {
		t.Fatal(err)
	}
	if len(stamper.got) != 0 {
		t.Fatalf("Django's form-only post already stamps; Go stamped %d more", len(stamper.got))
	}
}

func TestAFailedStampNeverChangesTheAnswer(t *testing.T) {
	stamper := &fakeStamper{err: errors.New("the database is away")}
	saver := &fakeSaver{answer: activities.Answer{Message: "Saved."}}
	service := NewService(nil).WithVisitSave(saver, nil).WithPresence(stamper, nil)

	answer, err := saveVisit(service)

	if err != nil || !answer.GetSaved() {
		t.Fatalf("a failed stamp must not fail the save: %v %v", answer, err)
	}
}

func TestAPageDrawerSaveWithoutDjangoStampsThePerson(t *testing.T) {
	stamper := &fakeStamper{}
	service := NewService(nil).WithPresence(stamper, nil)

	// No saver takes this form, so the answer is the unavailable one; the
	// person still made the request.
	_, _ = service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/activities/a1/cancel", Values: map[string]string{"reason": "rain"},
	}))

	want := presence.Request{Method: "POST", Path: pathPageDrawer, Bearer: true}
	if len(stamper.got) != 1 || stamper.got[0] != want {
		t.Fatalf("stamps = %+v, want one %+v", stamper.got, want)
	}
}

func TestAnInvalidDrawerRequestStampsNothing(t *testing.T) {
	stamper := &fakeStamper{}
	service := NewService(nil).WithPresence(stamper, nil)

	_, err := service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "https://elsewhere.example/activities/a1/cancel",
	}))

	if err == nil {
		t.Fatal("the path should be refused")
	}
	if len(stamper.got) != 0 {
		t.Fatalf("a refused path stamped %d times", len(stamper.got))
	}
}
