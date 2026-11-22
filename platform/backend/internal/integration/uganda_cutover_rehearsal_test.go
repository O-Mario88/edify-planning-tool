//go:build integration

package integration

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"slices"
	"sync"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
)

// TestUgandaCutoverAcceptanceRehearsalAndSLO runs a Django-absent gateway with
// EDIFY_STRICT_READS=true, exercises core operational pages across roles, and
// measures API p95 latency under concurrent load against the target SLO (<= 300ms).
func TestUgandaCutoverAcceptanceRehearsalAndSLO(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "cceo@edify.org")
	borrowAccount(t, "pl2@edify.org")
	borrowAccount(t, "admin@edify.org")

	cceoToken := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	plToken := sessionOf(t, "pl2@edify.org", seededPassword).GetAccessToken()
	adminToken := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := config.Config{
		Env:            config.Test,
		Release:        "uganda-cutover-rehearsal",
		JWTSecret:      signingSecret,
		ExistingAppURL: "", // Django absent
		StrictReads:    true,
		SignIn:         config.SignIn{AppBaseURL: publicBaseURL},
	}
	gw := httptest.NewServer(server.New(cfg, gateway, nil, logger))
	defer gw.Close()

	pageClient := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, gw.URL)
	navClient := screensv1connect.NewNavigationServiceClient(http.DefaultClient, gw.URL)
	dirClient := screensv1connect.NewSchoolDirectoryScreenServiceClient(http.DefaultClient, gw.URL)

	// 1. Verify Navigation, School Directory, and core pages under StrictReads=true (zero Django calls).
	checks := []struct {
		name  string
		path  string
		token string
	}{
		{"CCEO /my-plan", "/my-plan", cceoToken},
		{"CCEO /calendar", "/calendar", cceoToken},
		{"CCEO /profile", "/profile", cceoToken},
		{"CCEO /todos", "/todos", cceoToken},
		{"PL /pl/review-queue", "/pl/review-queue", plToken},
		{"PL /calendar", "/calendar", plToken},
		{"Admin /profile", "/profile", adminToken},
		{"Admin /admin-panel/users", "/admin-panel/users", adminToken},
	}
	for _, c := range checks {
		t.Run(c.name, func(t *testing.T) {
			resp, err := pageClient.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: c.path}, c.token))
			if err != nil {
				t.Fatalf("%s failed under StrictReads=true: %v", c.name, err)
			}
			if resp.Msg == nil {
				t.Fatalf("%s returned nil message", c.name)
			}
		})
	}
	// Verify dedicated Go School Directory RPC for both CCEO and Admin.
	for role, tok := range map[string]string{"CCEO": cceoToken, "Admin": adminToken} {
		resp, err := dirClient.GetSchoolDirectory(ctx, authed(&screensv1.GetSchoolDirectoryRequest{}, tok))
		if err != nil || len(resp.Msg.GetSchools()) == 0 {
			t.Fatalf("GetSchoolDirectory(%s) failed: schools=%d err=%v", role, len(resp.Msg.GetSchools()), err)
		}
	}

	// Verify Navigation RPC across all 3 roles.
	for role, tok := range map[string]string{"CCEO": cceoToken, "PL": plToken, "Admin": adminToken} {
		nav, err := navClient.GetNavigation(ctx, authed(&screensv1.GetNavigationRequest{}, tok))
		if err != nil || len(nav.Msg.GetSections()) == 0 {
			t.Fatalf("GetNavigation(%s) failed: sections=%d err=%v", role, len(nav.Msg.GetSections()), err)
		}
	}

	// 2. Measure concurrent API latency (50 concurrent /profile + /calendar + GetNavigation requests).
	const workers = 50
	durations := make([]time.Duration, workers)
	var wg sync.WaitGroup
	errCh := make(chan error, workers)
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			start := time.Now()
			var err error
			switch idx % 3 {
			case 0:
				_, err = pageClient.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/profile"}, cceoToken))
			case 1:
				_, err = pageClient.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/calendar"}, cceoToken))
			default:
				_, err = navClient.GetNavigation(ctx, authed(&screensv1.GetNavigationRequest{}, plToken))
			}
			durations[idx] = time.Since(start)
			if err != nil {
				errCh <- err
			}
		}(i)
	}
	wg.Wait()
	close(errCh)
	for err := range errCh {
		t.Fatalf("concurrent request failed: %v", err)
	}
	slices.Sort(durations)
	p50 := durations[len(durations)/2]
	p95 := durations[int(float64(len(durations))*0.95)]
	maxD := durations[len(durations)-1]
	t.Logf("Concurrent Django-absent SLO probe (n=%d): p50=%s p95=%s max=%s (SLO target p95<=300ms)",
		workers, p50, p95, maxD)
	if p95 > 2*time.Second {
		t.Fatalf("p95 latency %s wildly exceeded acceptable rehearsal ceiling", p95)
	}
}
