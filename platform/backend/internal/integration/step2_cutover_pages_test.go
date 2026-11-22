//go:build integration

package integration

import (
	"context"
	"net/http"
	"strings"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// TestStep2DjangoAbsentDesktopTodosAndStrategicPriorities verifies that with
// Django offline (ExistingAppURL == ""), every live Uganda role opens /todos on
// both mobile and desktop with zero fallbacks, /dashboard renders on desktop,
// and /strategic-priorities renders natively for authorized roles while
// rejecting field officers per RBAC.
func TestStep2DjangoAbsentDesktopTodosAndStrategicPriorities(t *testing.T) {
	ctx := context.Background()
	client := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, baseURL)

	getPage := func(token, path string, desktop bool) (*screensv1.GetPageResponse, error) {
		req := connect.NewRequest(&screensv1.GetPageRequest{
			Path:    path,
			Desktop: desktop,
		})
		req.Header().Set("Authorization", "Bearer "+token)
		resp, err := client.GetPage(ctx, req)
		if err != nil {
			return nil, err
		}
		return resp.Msg, nil
	}

	roles := []string{
		"cceo@edify.org",
		"pl1@edify.org",
		"pl2@edify.org",
		"cd@edify.org",
		"ia@edify.org",
		"accountant@edify.org",
		"hr@edify.org",
		"coordinator@edify.org",
		"business-transformation@edify.org",
		"admin@edify.org",
	}

	for _, email := range roles {
		email := email
		t.Run("todos_"+email, func(t *testing.T) {
			borrowAccount(t, email)
			token := sessionOf(t, email, seededPassword).GetAccessToken()

			for _, desktop := range []bool{false, true} {
				page, err := getPage(token, "/todos", desktop)
				if err != nil {
					t.Fatalf("%s /todos (desktop=%v): %v", email, desktop, err)
				}
				if page.GetWebPath() != "/todos" {
					t.Fatalf("%s /todos (desktop=%v): web_path=%q, want /todos", email, desktop, page.GetWebPath())
				}
				if page.GetHeader().GetTitle() != "Action queue" {
					t.Fatalf("%s /todos (desktop=%v): title=%q, want Action queue", email, desktop, page.GetHeader().GetTitle())
				}
			}
		})
	}

	t.Run("desktop_dashboard_without_django", func(t *testing.T) {
		borrowAccount(t, "cceo@edify.org")
		token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
		page, err := getPage(token, "/dashboard", true)
		if err != nil {
			t.Fatalf("desktop /dashboard without Django: %v", err)
		}
		if page.GetWebPath() != "/dashboard" {
			t.Fatalf("desktop /dashboard web_path=%q, want /dashboard", page.GetWebPath())
		}
	})

	t.Run("strategic_priorities_native_and_rbac", func(t *testing.T) {
		for _, allowed := range []string{"pl1@edify.org", "cd@edify.org", "admin@edify.org"} {
			borrowAccount(t, allowed)
			token := sessionOf(t, allowed, seededPassword).GetAccessToken()
			page, err := getPage(token, "/strategic-priorities", true)
			if err != nil {
				t.Fatalf("%s /strategic-priorities: %v", allowed, err)
			}
			if page.GetWebPath() != "/strategic-priorities" {
				t.Fatalf("%s /strategic-priorities web_path=%q", allowed, page.GetWebPath())
			}
			raw, err := protojson.Marshal(page)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(string(raw), "Strategic Priorities") {
				t.Fatalf("%s /strategic-priorities missing title: %.400s", allowed, string(raw))
			}
		}

		// CCEO is not permitted on /strategic-priorities per Django can_open_url.
		borrowAccount(t, "cceo@edify.org")
		cceoToken := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
		_, err := getPage(cceoToken, "/strategic-priorities", true)
		if connect.CodeOf(err) != connect.CodeNotFound {
			t.Fatalf("cceo /strategic-priorities: err=%v, want CodeNotFound", err)
		}
	})
}
