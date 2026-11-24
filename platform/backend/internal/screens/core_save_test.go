package screens

import (
	"context"
	"net/url"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

type fakeCoreSaver struct {
	got       []activities.CoreVisitRequest
	trainings []activities.CoreTrainingRequest
	assigned  []activities.CoreAssignRequest
	answer    activities.Answer
	err       error
}

func (f *fakeCoreSaver) ScheduleCoreVisit(_ context.Context, _ auth.Principal, req activities.CoreVisitRequest, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, req)
	return f.answer, f.err
}

func (f *fakeCoreSaver) ScheduleCoreTraining(_ context.Context, _ auth.Principal, req activities.CoreTrainingRequest, _ activities.Origin) (activities.Answer, error) {
	f.trainings = append(f.trainings, req)
	return f.answer, f.err
}

func (f *fakeCoreSaver) AssignCorePartner(_ context.Context, _ auth.Principal, req activities.CoreAssignRequest, _ activities.Origin) (activities.Answer, error) {
	f.assigned = append(f.assigned, req)
	return f.answer, f.err
}

func TestTheCoreAssignFormSavesInGoWithoutDjango(t *testing.T) {
	saver := &fakeCoreSaver{answer: activities.Answer{Message: "Core support assigned to Build Africa successfully."}}
	service := NewService(nil).WithCoreVisitSave(saver, nil)

	answer, err := service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path:   "/core-schools/assign-partner?school_id=1045",
		Values: map[string]string{"partner_id": "p1", "purpose_of_visit": "ssa_support"},
	}))

	if err != nil || !answer.Msg.GetSaved() || len(saver.assigned) != 1 || saver.assigned[0].PartnerID != "p1" ||
		saver.assigned[0].SchoolCode != "1045" {
		t.Fatalf("answer %v, %v, got %+v", answer, err, saver.assigned)
	}
}

func TestTheCoreAssignFormStaysWithDjangoWhileDjangoIsThere(t *testing.T) {
	saver := &fakeCoreSaver{}
	fetcher := &formFetcher{}
	service := NewService(fetcher).WithCoreVisitSave(saver, nil)

	if _, err := service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path:   "/core-schools/assign-partner?school_id=1045",
		Values: map[string]string{"partner_id": "p1", "purpose_of_visit": "ssa_support"},
	})); err != nil {
		t.Fatal(err)
	}
	if len(saver.assigned) != 0 || len(fetcher.paths) != 1 {
		t.Fatalf("Go saved %d, Django was asked %v", len(saver.assigned), fetcher.paths)
	}
}

func TestTheCoreTrainingFormSavesInGoWithoutDjango(t *testing.T) {
	saver := &fakeCoreSaver{answer: activities.Answer{Message: "Core Training T1 scheduled successfully."}}
	service := NewService(nil).WithCoreVisitSave(saver, nil)

	answer, err := service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path:   "/core-schools/schedule-training?school_id=1045",
		Values: map[string]string{"catalogue_item_id": "c1", "scheduled_date": "2026-12-01"},
	}))

	if err != nil || !answer.Msg.GetSaved() || len(saver.trainings) != 1 || saver.trainings[0].CourseID != "c1" {
		t.Fatalf("answer %v, %v, got %+v", answer, err, saver.trainings)
	}
}

func saveCoreVisit(service *Service) (*screensv1.SaveDrawerResponse, error) {
	answer, err := service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/core-schools/schedule-visit?school_id=1045",
		Values: map[string]string{"purpose_of_visit": "training_follow_up", "scheduled_date": "2026-12-01",
			"visit_number": "2", "focus_intervention": "leadership"},
	}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestTheCoreVisitFormSavesInGoWithoutDjango(t *testing.T) {
	saver := &fakeCoreSaver{answer: activities.Answer{Message: "Core Visit V2 (Training Follow Up) scheduled successfully."}}
	service := NewService(nil).WithCoreVisitSave(saver, nil)

	answer, err := saveCoreVisit(service)

	if err != nil || !answer.GetSaved() || answer.GetMessage() != "Core Visit V2 (Training Follow Up) scheduled successfully." {
		t.Fatalf("answer = %v, %v", answer, err)
	}
	if len(saver.got) != 1 || saver.got[0].SchoolCode != "1045" || saver.got[0].VisitNumber != "2" {
		t.Fatalf("request = %+v", saver.got)
	}
}

func TestTheCoreVisitFormAnswersARefusalInItsWords(t *testing.T) {
	saver := &fakeCoreSaver{err: &activities.Refusal{Message: "That date has passed."}}
	service := NewService(nil).WithCoreVisitSave(saver, nil)

	answer, err := saveCoreVisit(service)

	if err != nil || answer.GetSaved() || answer.GetError() != "That date has passed." {
		t.Fatalf("answer = %v, %v", answer, err)
	}
}

func TestTheCoreVisitFormStaysWithDjangoWhileDjangoIsThere(t *testing.T) {
	saver := &fakeCoreSaver{}
	fetcher := &formFetcher{}
	service := NewService(fetcher).WithCoreVisitSave(saver, nil)

	if _, err := saveCoreVisit(service); err != nil {
		t.Fatal(err)
	}
	if len(saver.got) != 0 || len(fetcher.paths) != 1 {
		t.Fatalf("Go saved %d, Django was asked %v", len(saver.got), fetcher.paths)
	}
}

func TestAnotherDrawerNeverReachesTheCoreVisitSave(t *testing.T) {
	saver := &fakeCoreSaver{}
	service := NewService(&formFetcher{}).WithCoreVisitSave(saver, nil)
	_, _ = service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/core-schools/assign-partner?school_id=1045",
	}))
	if len(saver.got) != 0 {
		t.Fatalf("got %+v", saver.got)
	}
}

type fakeDecider struct {
	got    []activities.VisitDecision
	answer activities.Answer
	err    error
}

func (f *fakeDecider) DecideVisitRequest(_ context.Context, _ auth.Principal, d activities.VisitDecision, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, d)
	return f.answer, f.err
}

func decideVisit(service *Service, path string, values map[string]string) (*screensv1.SaveDrawerResponse, error) {
	answer, err := service.SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{Path: path, Values: values}))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func TestTheOwnersDecisionSavesInGoWithoutDjango(t *testing.T) {
	decider := &fakeDecider{answer: activities.Answer{Message: "Visit to Mpatta declined. The requester has been told."}}
	service := NewService(nil).WithVisitDecisions(decider)

	answer, err := decideVisit(service, "/planning/visit-requests/a1/decline", map[string]string{"reason": "the school is closed"})

	if err != nil || !answer.GetSaved() || len(decider.got) != 1 {
		t.Fatalf("answer %v, %v", answer, err)
	}
	if got := decider.got[0]; got != (activities.VisitDecision{ActivityID: "a1", Decision: "decline", Note: "the school is closed"}) {
		t.Fatalf("got %+v", got)
	}
}

func TestTheOwnersDecisionAnswersARefusalInItsWords(t *testing.T) {
	decider := &fakeDecider{err: &activities.Refusal{Message: "Give the requester a reason for declining."}}
	answer, err := decideVisit(NewService(nil).WithVisitDecisions(decider), "/planning/visit-requests/a1/decline", nil)
	if err != nil || answer.GetSaved() || answer.GetError() != "Give the requester a reason for declining." {
		t.Fatalf("answer %v, %v", answer, err)
	}
}

func TestTheOwnersDecisionStaysWithDjangoWhileDjangoIsThere(t *testing.T) {
	decider := &fakeDecider{}
	fetcher := &formFetcher{}
	if _, err := decideVisit(NewService(fetcher).WithVisitDecisions(decider), "/planning/visit-requests/a1/approve", nil); err != nil {
		t.Fatal(err)
	}
	if len(decider.got) != 0 || len(fetcher.paths) != 1 {
		t.Fatalf("Go decided %d, Django was asked %v", len(decider.got), fetcher.paths)
	}
}

func TestAnUnknownDecisionIsNotGos(t *testing.T) {
	decider := &fakeDecider{}
	_, _ = decideVisit(NewService(&formFetcher{}).WithVisitDecisions(decider), "/planning/visit-requests/a1/maybe", nil)
	if len(decider.got) != 0 {
		t.Fatalf("got %+v", decider.got)
	}
}

type fakeStarter struct {
	got []string
	err error
}

func (f *fakeStarter) EnterSalesforceID(_ context.Context, _ auth.Principal, id string, form url.Values, _ activities.Origin) (activities.CompleteAnswer, error) {
	f.got = append(f.got, id+"|"+form.Get("salesforce_id"))
	return activities.CompleteAnswer{Message: "Saved."}, f.err
}

func TestTheSalesforceIDSavesInGoWithoutDjango(t *testing.T) {
	starter := &fakeStarter{}
	answer, err := decideVisit(NewService(nil).WithActivityLifecycle(starter), "/activities/a1/salesforce-id/action",
		map[string]string{"salesforce_id": "SVE-1"})
	if err != nil || !answer.GetSaved() || len(starter.got) != 1 || starter.got[0] != "a1|SVE-1" {
		t.Fatalf("answer %v, %v, got %v", answer, err, starter.got)
	}
}

func (f *fakeStarter) StartActivity(_ context.Context, _ auth.Principal, id, notes string, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, id+"|"+notes)
	return activities.Answer{Message: "Saved."}, f.err
}

func TestStartActivitySavesInGoWithoutDjango(t *testing.T) {
	starter := &fakeStarter{}
	answer, err := decideVisit(NewService(nil).WithActivityLifecycle(starter), "/activities/a1/start/action", map[string]string{"notes": "on site"})
	if err != nil || !answer.GetSaved() || len(starter.got) != 1 || starter.got[0] != "a1|on site" {
		t.Fatalf("answer %v, %v, got %v", answer, err, starter.got)
	}
}

func (f *fakeStarter) SubmitForReview(_ context.Context, _ auth.Principal, id string, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, id+"|submit")
	return activities.Answer{Message: "Saved."}, f.err
}

func TestSubmitForReviewSavesInGoWithoutDjango(t *testing.T) {
	starter := &fakeStarter{}
	answer, err := decideVisit(NewService(nil).WithActivityLifecycle(starter), "/activities/a1/submit/action", nil)
	if err != nil || !answer.GetSaved() || len(starter.got) != 1 || starter.got[0] != "a1|submit" {
		t.Fatalf("answer %v, %v, got %v", answer, err, starter.got)
	}
	starter.err = &activities.Refusal{Message: "Activity is not ready to be submitted for review."}
	answer, err = decideVisit(NewService(nil).WithActivityLifecycle(starter), "/activities/a1/submit/action", nil)
	if err != nil || answer.GetSaved() || answer.GetError() != "Submission Error: Activity is not ready to be submitted for review." {
		t.Fatalf("refusal %v, %v", answer, err)
	}
}

func (f *fakeStarter) RecordAttendance(_ context.Context, _ auth.Principal, id string, form url.Values, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, id+"|"+form.Get("teachers_attended"))
	return activities.Answer{Message: "Saved."}, f.err
}

func TestAttendanceSavesInGoWithoutDjango(t *testing.T) {
	starter := &fakeStarter{}
	answer, err := decideVisit(NewService(nil).WithActivityLifecycle(starter), "/activities/a1/attendance/action",
		map[string]string{"teachers_attended": "12"})
	if err != nil || !answer.GetSaved() || len(starter.got) != 1 || starter.got[0] != "a1|12" {
		t.Fatalf("answer %v, %v, got %v", answer, err, starter.got)
	}
	starter.err = &activities.Refusal{Message: "teachersAttended cannot be negative."}
	answer, err = decideVisit(NewService(nil).WithActivityLifecycle(starter), "/activities/a1/attendance/action", nil)
	if err != nil || answer.GetSaved() || answer.GetError() != "Attendance Error: teachersAttended cannot be negative." {
		t.Fatalf("refusal %v, %v", answer, err)
	}
}

func TestStartActivityStaysWithDjangoWhileDjangoIsThere(t *testing.T) {
	starter := &fakeStarter{}
	fetcher := &formFetcher{}
	if _, err := decideVisit(NewService(fetcher).WithActivityLifecycle(starter), "/activities/a1/start/action", nil); err != nil {
		t.Fatal(err)
	}
	if len(starter.got) != 0 || len(fetcher.paths) != 1 {
		t.Fatalf("Go started %d, Django was asked %v", len(starter.got), fetcher.paths)
	}
}
