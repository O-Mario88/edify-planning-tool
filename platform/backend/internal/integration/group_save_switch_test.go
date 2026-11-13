//go:build integration

package integration

import (
	"context"
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

// The app's group Reschedule and group Cancel saves reach Go only behind
// EDIFY_GO_SAVES=group_reschedule / group_cancel (docs/migration/33): with
// the switches unset, a gateway loaded from its environment forwards each
// group whole to the existing application, asks it for no form and writes
// nothing itself; and neither switch can be loaded in production or in the
// test environment.
func TestTheGoGroupSavesAreOffByDefaultAndRefusedInProduction(t *testing.T) {
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
	if cfg.GoSaves.GroupReschedule || cfg.GoSaves.GroupCancel {
		t.Fatal("the Go group saves must be off unless EDIFY_GO_SAVES names them")
	}
	gatewayServer := httptest.NewServer(server.New(cfg, gateway, nil, slog.New(slog.NewTextHandler(io.Discard, nil))))
	defer gatewayServer.Close()
	var userID string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'cceo@edify.org'`).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, gatewayServer.URL)
	for _, path := range []string{"/activity-selection/reschedule?ids=act1,act2", "/activity-selection/cancel?ids=act1,act2"} {
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{
			Path: path, Values: map[string]string{"scheduled_date": "2026-11-27", "reason": "exams"},
		}, token(t, userID, "CCEO", time.Minute)))
		if err != nil {
			t.Fatal(err)
		}
		if answer.Msg.GetError() != "the existing application's answer" {
			t.Fatalf("%s: the save was not the existing application's: %v", path, answer.Msg)
		}
	}
	mu.Lock()
	calls := strings.Join(asked, "; ")
	mu.Unlock()
	if calls != "POST /api/mobile/v1/drawer; POST /api/mobile/v1/drawer" {
		t.Fatalf("the existing application was asked %q", calls)
	}
	for _, saves := range []string{config.SaveGroupReschedule, config.SaveGroupCancel} {
		environment["EDIFY_GO_SAVES"] = saves
		for _, env := range []string{"production", "test"} {
			environment["EDIFY_ENV"] = env
			cfg, err := config.Load(getenv)
			if err == nil || cfg.GoSaves.GroupReschedule || cfg.GoSaves.GroupCancel {
				t.Fatalf("%s, %s: the switch loaded (%v)", saves, env, cfg.GoSaves)
			}
		}
	}
}
