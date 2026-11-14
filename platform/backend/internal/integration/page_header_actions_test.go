//go:build integration

package integration

import (
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The gateway under test has no existing application behind it, so these
// header buttons are Go's own.
func TestHeaderButtonsCarryTheirKindAndThePagesQuery(t *testing.T) {
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()

	planning, err := pageOf(token, "/planning", map[string]string{"tab": "core", "search": "a b"})
	if err != nil {
		t.Fatal(err)
	}
	assertActions(t, "Planning", planning.GetHeader().GetActions(), []wantAction{
		{"export", "/planning?export=csv&search=a+b&tab=core", false, true},
		{"plan_field_event", "/work-plan/add", true, false},
		{"recent_changes", "/planning/recent-changes", true, false},
	})

	clusters, err := pageOf(token, "/clusters", nil)
	if err != nil {
		t.Fatal(err)
	}
	actions := clusters.GetHeader().GetActions()
	if len(actions) == 0 || !actions[0].GetPrimary() || actions[0].GetKey() != "create_cluster" {
		t.Fatalf("Clusters opens on its one primary button: %v", actions)
	}
	if last := actions[len(actions)-1]; last.GetKey() != "export" || !last.GetDownload() || last.GetHref() != "/clusters?export=csv" {
		t.Fatalf("Clusters ends on Export: %v", last)
	}
}

type wantAction struct {
	key, href        string
	drawer, download bool
}

func assertActions(t *testing.T, page string, got []*screensv1.PageAction, want []wantAction) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("%s: %v, want %v", page, got, want)
	}
	for i, w := range want {
		g := got[i]
		if g.GetKey() != w.key || g.GetHref() != w.href || g.GetDrawer() != w.drawer || g.GetDownload() != w.download || !g.GetEnabled() {
			t.Errorf("%s button %d: %v, want %+v", page, i, g, w)
		}
	}
}
