//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// A partner organisation's login setup drawer and its save are Go's: the
// Admin's drawer says no login is linked; a choice the rules refuse draws
// the drawer again with the reason at its top; "no login yet" is recorded;
// an invite creates a Partner Admin account and links it; the Country
// Director is refused in Django's words.
func TestAdminSetsUpAPartnerLoginInGo(t *testing.T) {
	ctx := context.Background()
	const email = "go.partner.login@edify.test"
	removeCreated(t, email)
	var id, name, status string
	if err := admin.QueryRow(ctx, `SELECT id, name, user_setup_status FROM partner
WHERE deleted_at IS NULL AND user_id IS NULL ORDER BY name LIMIT 1`).Scan(&id, &name, &status); err != nil {
		t.Fatalf("a partner without a login: %v", err)
	}
	t.Cleanup(func() {
		// Runs before removeCreated's cleanup: the partner holds the account.
		if _, err := admin.Exec(ctx, `UPDATE partner SET user_id = NULL, user_setup_status = $2 WHERE id = $1`, id, status); err != nil {
			t.Errorf("restoring the partner: %v", err)
		}
	})
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	path := "/partners/" + id + "/user-setup"
	borrowAccount(t, "admin@edify.org")
	token := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	opened, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, token))
	if err != nil || opened.Msg.GetDrawer().GetTitle() != "Set up login for "+name ||
		opened.Msg.GetDrawer().GetItems()[0].GetText() != "Current login: None linked" {
		t.Fatalf("the drawer: %v %v", opened, err)
	}
	save := func(values map[string]string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path, Values: values}, token))
		if err != nil {
			t.Fatalf("saving: %v", err)
		}
		return answer.Msg
	}
	if r := save(map[string]string{"mode": "link", "email": "cceo1@edify.org"}); r.GetSaved() ||
		r.GetDrawer().GetItems()[0].GetNote().GetTone() != "danger" ||
		r.GetDrawer().GetItems()[0].GetNote().GetText() == "" {
		t.Fatalf("linking a staff account: %+v", r)
	}
	if r := save(map[string]string{"mode": "not_required"}); !r.GetSaved() ||
		r.GetMessage() != name+": marked as needing no login yet." {
		t.Fatalf("no login yet: %+v", r)
	}
	if r := save(map[string]string{"mode": "invite", "email": email, "login_name": "Go Test " + email}); !r.GetSaved() ||
		r.GetMessage() != name+": login linked." {
		t.Fatalf("an invite: %+v", r)
	}
	var role, stored string
	if err := admin.QueryRow(ctx, `SELECT u.active_role, p.user_setup_status FROM partner p JOIN "user" u ON u.id = p.user_id
WHERE p.id = $1`, id).Scan(&role, &stored); err != nil || role != "PartnerAdmin" || stored != "configured" {
		t.Fatalf("the linked login: %q %q %v", role, stored, err)
	}
	borrowAccount(t, "cd@edify.org")
	cd := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, cd)); err != nil ||
		r.Msg.GetRefusal() != "Only a user administrator can set up partner logins." {
		t.Fatalf("the Country Director: %v %v", r, err)
	}
}
