package screens

import (
	"context"
	"testing"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Go's stand-in forms answer only with the existing application absent:
// beside it they replaced its full forms for every client.
func TestNativeFormsStandAsideWhileTheExistingApplicationAnswers(t *testing.T) {
	existing := &recordingFetcher{}
	withDjango := NewService(existing).WithSchoolDB(&pgxpool.Pool{}, nil)
	if withDjango.nativeForms() {
		t.Fatal("native forms answered with the existing application configured")
	}
	if !NewService(nil).WithSchoolDB(&pgxpool.Pool{}, nil).nativeForms() {
		t.Fatal("native forms refused with the existing application absent")
	}
	ctx := auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "CCEO"}})
	for _, path := range []string{"/schools/s1/edit-drawer", "/clusters/c1/edit-drawer", "/my-plan/a1/complete-drawer"} {
		before := len(existing.paths)
		if _, err := withDjango.GetDrawer(ctx, connect.NewRequest(&screensv1.GetDrawerRequest{Path: path})); err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		if len(existing.paths) != before+1 {
			t.Fatalf("%s was not handed to the existing application", path)
		}
	}
}

// A drawer name is shared by several records; the activity forms answer only
// an activity's address.
func TestPlanDrawerMatchesOnlyAnActivityOnMyPlan(t *testing.T) {
	for path, want := range map[string]bool{
		"/my-plan/a1/complete-drawer":             true,
		"/my-plan/a1/edit-drawer":                 true,
		"/schools/s1/edit-drawer":                 false,
		"/clusters/c1/edit-drawer":                false,
		"/partners/p1/edit-drawer":                false,
		"/ia/partner-evidence/a1/complete-drawer": false,
	} {
		kind := "edit"
		if path == "/my-plan/a1/complete-drawer" || path == "/ia/partner-evidence/a1/complete-drawer" {
			kind = "complete"
		}
		if got := planDrawer(path, kind); got != want {
			t.Errorf("planDrawer(%q, %q) = %v, want %v", path, kind, got, want)
		}
	}
}
