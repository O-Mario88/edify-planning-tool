//go:build integration

package integration

import (
	"context"
	"net/http"
	"slices"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

func navigationOf(token string) (*screensv1.GetNavigationResponse, error) {
	answer, err := screensv1connect.NewNavigationServiceClient(http.DefaultClient, baseURL).GetNavigation(context.Background(),
		authed(&screensv1.GetNavigationRequest{}, token))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func barKeys(n *screensv1.GetNavigationResponse) []string {
	out := []string{}
	for _, i := range n.GetBottom() {
		out = append(out, i.GetPageKey())
	}
	return out
}

func menuKeys(n *screensv1.GetNavigationResponse) []string {
	out := []string{}
	for _, s := range n.GetSections() {
		for _, i := range s.GetItems() {
			out = append(out, i.GetPageKey())
		}
	}
	return out
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheNavigationIsTheReadersRolesMenu(t *testing.T) {
	cases := []struct {
		email   string
		bar     []string
		has     string
		hasNot  string
		section string
	}{
		{"cceo17@edify.org", []string{"home", "my_plan", "schools", "messages"}, "clusters", "users", "DAILY"},
		{"pl2@edify.org", []string{"home", "my_plan", "team_planning_oversight", "messages"}, "team_planning_oversight", "users", "OVERSIGHT"},
		{"admin@edify.org", []string{"home", "admin_support_queue", "system_health", "messages"}, "users", "", "WEEKLY"},
	}
	for _, c := range cases {
		t.Run(c.email, func(t *testing.T) {
			borrowAccount(t, c.email)
			nav, err := navigationOf(sessionOf(t, c.email, seededPassword).GetAccessToken())
			if err != nil {
				t.Fatal(err)
			}
			if got := barKeys(nav); !slices.Equal(got, c.bar) {
				t.Errorf("bar %v, want %v", got, c.bar)
			}
			menu := menuKeys(nav)
			if !slices.Contains(menu, c.has) || (c.hasNot != "" && slices.Contains(menu, c.hasNot)) {
				t.Errorf("menu %v: want %s and not %q", menu, c.has, c.hasNot)
			}
			labels := []string{}
			for _, s := range nav.GetSections() {
				labels = append(labels, s.GetLabel())
			}
			if !slices.Contains(labels, c.section) {
				t.Errorf("sections %v lack %s", labels, c.section)
			}
			for _, i := range nav.GetBottom() {
				if i.GetIconSvg() == "" || i.GetUrl() == "" {
					t.Errorf("%s has no icon or url", i.GetPageKey())
				}
			}
		})
	}
}

func TestTheNavigationNeedsASignedInReader(t *testing.T) {
	if _, err := navigationOf(""); connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Fatalf("got %v, want unauthenticated", err)
	}
}
