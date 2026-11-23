package screens

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
)

type fakePLReviewer struct {
	approved []string
	returned []string
	seen     origin.Origin
	err      error
}

func TestAReviewDecisionCarriesWhereItCameFrom(t *testing.T) {
	reviewer := &fakePLReviewer{}
	svc := NewService(nil).WithStrictReads(true).WithPLReviewSave(reviewer, nil)
	ctx := auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{UserID: "pl1", ActiveRole: "Program Lead"}})
	request := connect.NewRequest(&screensv1.SaveDrawerRequest{Path: "/pl/review-queue/act123/drawer"})
	request.Header().Set("User-Agent", "edify-test")
	if _, err := svc.SaveDrawer(ctx, request); err != nil {
		t.Fatal(err)
	}
	if reviewer.seen.UserAgent != "edify-test" {
		t.Fatalf("origin = %+v", reviewer.seen)
	}
}

func (f *fakePLReviewer) Approve(ctx context.Context, _ auth.Principal, activityID string) (plreview.ReviewResult, error) {
	f.seen, _ = origin.From(ctx)
	f.approved = append(f.approved, activityID)
	if f.err != nil {
		return plreview.ReviewResult{}, f.err
	}
	return plreview.ReviewResult{ActivityID: activityID, Status: "ia_verified"}, nil
}

func (f *fakePLReviewer) Return(_ context.Context, _ auth.Principal, activityID string, reasons []string, written string) (plreview.ReviewResult, error) {
	f.returned = append(f.returned, activityID+":"+strings.Join(append(append([]string{}, reasons...), written), "|"))
	if f.err != nil {
		return plreview.ReviewResult{}, f.err
	}
	return plreview.ReviewResult{ActivityID: activityID, Status: "returned_by_pl", Reason: written}, nil
}

func TestTheReviewFormsSaveWhereTheyOpen(t *testing.T) {
	reviewer := &fakePLReviewer{}
	svc := NewService(nil).WithStrictReads(true).WithPLReviewSave(reviewer, nil)
	ctx := auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{UserID: "pl1", ActiveRole: "Program Lead"}})

	verified, err := svc.SaveDrawer(ctx, connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/pl/review-queue/act123/drawer?from=partner-trainings",
	}))
	if err != nil || verified.Msg.GetMessage() != "Completion verified and marked complete." {
		t.Fatalf("verify: %v %v", verified, err)
	}
	wrong := "Wrong school, cluster or activity date"
	returned, err := svc.SaveDrawer(ctx, connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/pl/review-queue/act123/return-drawer",
		Values: map[string]string{
			"reasons": "Participants not entered in Salesforce," + plreview.ReturnReasonValue(wrong),
			"reason":  " Enter the 12 teachers. ",
		},
	}))
	if err != nil || returned.Msg.GetMessage() != "Activity returned to CCEO for corrections." {
		t.Fatalf("return: %v %v", returned, err)
	}
	if len(reviewer.approved) != 1 || reviewer.approved[0] != "act123" {
		t.Fatalf("approved = %v", reviewer.approved)
	}
	want := "act123:Participants not entered in Salesforce|" + wrong + "|Enter the 12 teachers."
	if len(reviewer.returned) != 1 || reviewer.returned[0] != want {
		t.Fatalf("returned = %v", reviewer.returned)
	}
}

func TestAMissingCompletionIsNotFound(t *testing.T) {
	svc := NewService(nil).WithPLReviewSave(&fakePLReviewer{
		err: &plreview.ReviewRefusal{Message: "Activity not found.", NotFound: true},
	}, nil)
	ctx := auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{UserID: "pl1", ActiveRole: "Program Lead"}})
	_, served, err := svc.plReviewInGo(ctx, &screensv1.SaveDrawerRequest{Path: "/pl/review-queue/nope/confirm"})
	if !served || connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("served=%v err=%v", served, err)
	}
}

func TestPLReviewSaveRunsWithoutDjangoOrFormOnly(t *testing.T) {
	tracker := NewFallbackTracker()
	reviewer := &fakePLReviewer{}
	// existingApp is nil: zero Django server possible.
	svc := NewService(nil).WithStrictReads(true).WithFallbackTracker(tracker).WithPLReviewSave(reviewer, nil)
	ctx := auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{UserID: "pl1", ActiveRole: "Program Lead"}})

	resp, err := svc.SaveDrawer(ctx, connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/pl/review-queue/act123/confirm",
	}))
	if err != nil || !resp.Msg.GetSaved() {
		t.Fatalf("confirm failed: resp=%v err=%v", resp, err)
	}
	resp2, err := svc.SaveDrawer(ctx, connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path:   "/pl/review-queue/act123/return",
		Values: map[string]string{"reason": "Fix teacher count"},
	}))
	if err != nil || !resp2.Msg.GetSaved() {
		t.Fatalf("return failed: resp=%v err=%v", resp2, err)
	}
	if len(reviewer.approved) != 1 || reviewer.approved[0] != "act123" {
		t.Fatalf("approved = %v", reviewer.approved)
	}
	if len(reviewer.returned) != 1 || reviewer.returned[0] != "act123:Fix teacher count" {
		// No ticks: only the written words reach the service.
		t.Fatalf("returned = %v", reviewer.returned)
	}
	if tracker.Total() != 0 {
		t.Fatalf("expected 0 Django fallback attempts, got %d (%+v)", tracker.Total(), tracker.Counts())
	}
}
