package screens

import (
	"context"
	"errors"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

type failingFetcher struct{ err error }

func (f failingFetcher) Get(context.Context, string, proto.Message) error { return f.err }
func (f failingFetcher) Post(context.Context, string, proto.Message, proto.Message) error {
	return f.err
}

func TestFallbackTrackerCountsForwardedBlockedAndFailedAttempts(t *testing.T) {
	ctx := context.Background()

	// 1. Forwarded read
	tracker := NewFallbackTracker()
	svc := NewService(&recordingFetcher{}).WithFallbackTracker(tracker)
	if _, err := svc.GetHome(ctx, connect.NewRequest(&screensv1.GetHomeRequest{})); err != nil {
		t.Fatal(err)
	}
	if got := tracker.Total(); got != 1 {
		t.Fatalf("forwarded total = %d, want 1", got)
	}
	if got := tracker.Counts()[FallbackKey{Service: "HomeScreenService", Operation: "GET /api/mobile/v1/home", Outcome: FallbackForwarded}]; got != 1 {
		t.Fatalf("unexpected counts: %+v", tracker.Counts())
	}

	// 2. Blocked read under StrictReads still counts as an attempted call
	tracker.Reset()
	strict := NewService(&recordingFetcher{}).WithStrictReads(true).WithFallbackTracker(tracker)
	if _, err := strict.GetHome(ctx, connect.NewRequest(&screensv1.GetHomeRequest{})); err == nil {
		t.Fatal("expected unavailable under strict reads")
	}
	if got := tracker.Counts()[FallbackKey{Service: "HomeScreenService", Operation: "GET /api/mobile/v1/home", Outcome: FallbackBlocked}]; got != 1 {
		t.Fatalf("expected 1 blocked attempt, got %+v", tracker.Counts())
	}

	// 3. Failed upstream call counts as failed
	tracker.Reset()
	failing := NewService(failingFetcher{err: errors.New("boom")}).WithFallbackTracker(tracker)
	if _, err := failing.GetExport(ctx, connect.NewRequest(&screensv1.GetExportRequest{JobId: "job1234567890abcdef"})); err == nil {
		t.Fatal("expected error")
	}
	if got := tracker.Counts()[FallbackKey{Service: "ExportService", Operation: "GET /api/mobile/v1/exports/{id}", Outcome: FallbackFailed}]; got != 1 {
		t.Fatalf("expected 1 failed export attempt, got %+v", tracker.Counts())
	}
}

func TestRedactPathStripsQueryAndLongIDs(t *testing.T) {
	got := redactPath("/api/mobile/v1/schools/cmw9p7wgx00pmg4ekhe4m/drawers/edit?token=secret&q=john")
	want := "/api/mobile/v1/schools/{id}/drawers/edit"
	if got != want {
		t.Fatalf("redactPath = %q, want %q", got, want)
	}
}
