//go:build integration

package integration

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
)

// The app's Schedule save reaches Go only behind EDIFY_GO_SAVES (27 §27.10):
// with the switch unset, a gateway loaded from its environment forwards the
// save to the existing application exactly as before, asks it for no form,
// and writes nothing itself; and the switch cannot be loaded in production
// or in the test environment.
func TestTheGoVisitSaveIsOffByDefaultAndRefusedInProduction(t *testing.T) {
	ctx := context.Background()
	var mu sync.Mutex
	var asked []string
	existing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		asked = append(asked, r.Method+" "+r.URL.RequestURI())
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"saved": false, "error": "the existing application's answer"}`)
	}))
	defer existing.Close()

	environment := map[string]string{
		"EDIFY_ENV": "development", "EDIFY_DATABASE_URL": "postgresql://localhost/edify_gorn_test",
		"EDIFY_JWT_SECRET": signingSecret, "EDIFY_EXISTING_APP_URL": existing.URL,
		"EDIFY_INTERNAL_KEY": "integration-internal-key-0123456789abcdef",
	}
	getenv := func(key string) string { return environment[key] }
	cfg, err := config.Load(getenv)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.GoSaves.ScheduleVisit {
		t.Fatal("the Go visit save must be off unless EDIFY_GO_SAVES names it")
	}
	gatewayServer := httptest.NewServer(server.New(cfg, gateway, nil, slog.New(slog.NewTextHandler(io.Discard, nil))))
	defer gatewayServer.Close()

	var userID, schoolID string
	if err := admin.QueryRow(ctx, `SELECT u.id, s.id FROM "user" u
JOIN staff_profile sp ON sp.user_id = u.id
JOIN school s ON s.account_owner_id = sp.id AND s.deleted_at IS NULL
WHERE u.email = 'cceo@edify.org' LIMIT 1`).Scan(&userID, &schoolID); err != nil {
		t.Fatal(err)
	}
	var before int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity WHERE school_id = $1`, schoolID).Scan(&before); err != nil {
		t.Fatal(err)
	}
	drawers := screensv1connect.NewPlanningDrawerServiceClient(http.DefaultClient, gatewayServer.URL)
	answer, err := drawers.SavePlanningDrawer(ctx, authed(&screensv1.SavePlanningDrawerRequest{
		SchoolId: schoolID, Kind: "schedule", Values: map[string]string{
			"purpose_of_visit": "donor_visit", "scheduled_date": time.Now().AddDate(0, 0, 14).Format(time.DateOnly),
			"executor_type": "staff", "delivery_type": "staff",
		},
	}, token(t, userID, "CCEO", time.Minute)))
	if err != nil {
		t.Fatal(err)
	}
	if answer.Msg.GetError() != "the existing application's answer" {
		t.Fatalf("the save was not the existing application's: %v", answer.Msg)
	}
	mu.Lock()
	calls := strings.Join(asked, "; ")
	mu.Unlock()
	if calls != "POST /api/mobile/v1/schools/"+schoolID+"/planning/schedule" {
		t.Fatalf("the existing application was asked %q", calls)
	}
	var after int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity WHERE school_id = $1`, schoolID).Scan(&after); err != nil {
		t.Fatal(err)
	}
	if after != before {
		t.Fatalf("activities %d → %d: Go wrote a visit with the switch off", before, after)
	}

	environment["EDIFY_GO_SAVES"] = config.SaveScheduleVisit
	for _, env := range []string{"production", "test"} {
		environment["EDIFY_ENV"] = env
		cfg, err := config.Load(getenv)
		if err == nil || cfg.GoSaves.ScheduleVisit {
			t.Fatalf("%s: the switch loaded (%v)", env, cfg.GoSaves)
		}
		if env == "production" && !errors.Is(err, config.ErrProductionNotApproved) {
			t.Fatalf("production: %v", err)
		}
	}
}

// The app's Cancel save reaches Go only behind EDIFY_GO_SAVES=cancel_visit
// (docs/migration/30): with the switch unset the drawer's save is forwarded
// to the existing application as before, with no form asked for, and the
// switch cannot be loaded in production or in the test environment.
func TestTheGoCancelIsOffByDefaultAndRefusedInProduction(t *testing.T) {
	ctx := context.Background()
	var mu sync.Mutex
	var asked []string
	existing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		asked = append(asked, r.Method+" "+r.URL.RequestURI())
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"saved": false, "error": "the existing application's answer"}`)
	}))
	defer existing.Close()
	environment := map[string]string{
		"EDIFY_ENV": "development", "EDIFY_DATABASE_URL": "postgresql://localhost/edify_gorn_test",
		"EDIFY_JWT_SECRET": signingSecret, "EDIFY_EXISTING_APP_URL": existing.URL,
		"EDIFY_INTERNAL_KEY": "integration-internal-key-0123456789abcdef",
	}
	getenv := func(key string) string { return environment[key] }
	cfg, err := config.Load(getenv)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.GoSaves.CancelVisit {
		t.Fatal("the Go cancel must be off unless EDIFY_GO_SAVES names it")
	}
	gatewayServer := httptest.NewServer(server.New(cfg, gateway, nil, slog.New(slog.NewTextHandler(io.Discard, nil))))
	defer gatewayServer.Close()
	var userID string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'cceo@edify.org'`).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, gatewayServer.URL)
	answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{
		Path: "/my-plan/act1/cancel-drawer", Values: map[string]string{"reason": "the school closed"},
	}, token(t, userID, "CCEO", time.Minute)))
	if err != nil {
		t.Fatal(err)
	}
	if answer.Msg.GetError() != "the existing application's answer" {
		t.Fatalf("the save was not the existing application's: %v", answer.Msg)
	}
	mu.Lock()
	calls := strings.Join(asked, "; ")
	mu.Unlock()
	if calls != "POST /api/mobile/v1/drawer" {
		t.Fatalf("the existing application was asked %q", calls)
	}
	environment["EDIFY_GO_SAVES"] = config.SaveCancelVisit
	for _, env := range []string{"production", "test"} {
		environment["EDIFY_ENV"] = env
		cfg, err := config.Load(getenv)
		if err == nil || cfg.GoSaves.CancelVisit {
			t.Fatalf("%s: the switch loaded (%v)", env, cfg.GoSaves)
		}
	}
}
