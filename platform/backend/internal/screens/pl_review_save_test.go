package screens

import (
	"context"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
)

type fakePLReviewer struct {
	approved []string
	returned []string
	err      error
}

func (f *fakePLReviewer) Approve(_ context.Context, _ auth.Principal, activityID string) (plreview.ReviewResult, error) {
	f.approved = append(f.approved, activityID)
	if f.err != nil {
		return plreview.ReviewResult{}, f.err
	}
	return plreview.ReviewResult{ActivityID: activityID, Status: "ia_verified"}, nil
}

func (f *fakePLReviewer) Return(_ context.Context, _ auth.Principal, activityID, reason string) (plreview.ReviewResult, error) {
	f.returned = append(f.returned, activityID+":"+reason)
	if f.err != nil {
		return plreview.ReviewResult{}, f.err
	}
	return plreview.ReviewResult{ActivityID: activityID, Status: "returned_by_pl", Reason: reason}, nil
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
		t.Fatalf("returned = %v", reviewer.returned)
	}
	if tracker.Total() != 0 {
		t.Fatalf("expected 0 Django fallback attempts, got %d (%+v)", tracker.Total(), tracker.Counts())
	}
}
