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
				if email == "pl1@edify.org" && !desktop {
					raw, err := protojson.Marshal(page)
					if err != nil {
						t.Fatal(err)
					}
					body := string(raw)
					// The queue's size depends on the seed and the day, so the
					// header's count is held to the Do next band's.
					var headerOpen, bandOpen string
					for _, badge := range page.GetHeader().GetBadges() {
						if strings.HasSuffix(badge.GetText(), " open") {
							headerOpen = badge.GetText()
						}
					}
					for _, block := range page.GetBlocks() {
						if list := block.GetList(); list != nil && list.GetTitle() == "Do next" {
							bandOpen = list.GetCount()
						}
					}
					if headerOpen == "" || headerOpen == "0 open" || headerOpen != bandOpen {
						t.Fatalf("pl1@edify.org /todos counts differ: header %q, Do next %q", headerOpen, bandOpen)
					}
					if want := "Follow up SSA collection with CCEOs"; !strings.Contains(body, want) {
						t.Fatalf("pl1@edify.org /todos missing %q: %.600s", want, body)
					}
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

	t.Run("all_bucket1_2_3_pages_native_without_django", func(t *testing.T) {
		cases := []struct {
			email string
			path  string
		}{
			{"cceo@edify.org", "/core-schools"},
			{"cceo@edify.org", "/personal-time-off/"},
			{"cceo@edify.org", "/my-professional-development"},
			{"cceo@edify.org", "/actions/mine"},
			{"cceo@edify.org", "/my-targets"},
			{"pl1@edify.org", "/leave/tracker"},
			{"pl1@edify.org", "/target-distribution/team"},
			{"pl1@edify.org", "/priorities/guidance"},
			{"cd@edify.org", "/country-planning-oversight/"},
			{"cd@edify.org", "/analytics/country-director/drilldown"},
			{"ia@edify.org", "/ia/learning/"},
			{"ia@edify.org", "/ssa/unmatched"},
			{"ia@edify.org", "/ia/impact-reports/"},
			{"ia@edify.org", "/ia/lending-evidence/"},
			{"admin@edify.org", "/system-health"},
			{"admin@edify.org", "/platform-health"},
		}
		toks := map[string]string{}
		for _, tc := range cases {
			tok, ok := toks[tc.email]
			if !ok {
				borrowAccount(t, tc.email)
				tok = sessionOf(t, tc.email, seededPassword).GetAccessToken()
				toks[tc.email] = tok
			}
			page, err := getPage(tok, tc.path, true)
			if err != nil {
				t.Fatalf("%s %s: %v", tc.email, tc.path, err)
			}
			if page.GetHeader().GetTitle() == "" {
				t.Fatalf("%s %s: empty page header title", tc.email, tc.path)
			}
		}
		// The Monthly General Budget's old address sends its reader to the
		// unified Budget page (country_budget_view).
		for _, path := range []string{"/country-budget", "/country-budget/"} {
			page, err := getPage(toks["cd@edify.org"], path, true)
			if err != nil || page.GetRedirect() != "/budget" {
				t.Fatalf("cd %s: %v, redirect %q, want /budget", path, err, page.GetRedirect())
			}
		}
	})
}
