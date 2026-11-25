//go:build integration

package integration

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// The Users page's Reset password drawer and its save are Go's: the drawer
// names the account; a password the policy refuses is refused in its words;
// one it accepts is set as a one-time password; HR has no Users page.
func TestAdminResetsAPasswordInGo(t *testing.T) {
	ctx := context.Background()
	var id, hash string
	var mustChangeBefore bool
	if err := admin.QueryRow(ctx, `SELECT id, password, must_change_password FROM "user" WHERE email = 'cceo1@edify.org'`).
		Scan(&id, &hash, &mustChangeBefore); err != nil {
		t.Fatalf("the account: %v", err)
	}
	t.Cleanup(func() {
		// Other tests sign in as this account with the seeded password.
		if _, err := admin.Exec(ctx, `UPDATE "user" SET password = $2, must_change_password = $3 WHERE id = $1`, id, hash,
			mustChangeBefore); err != nil {
			t.Errorf("restoring the account: %v", err)
		}
	})
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	path := "/admin-panel/users/" + id + "?drawer=password"
	borrowAccount(t, "admin@edify.org")
	token := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	opened, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, token))
	if err != nil || opened.Msg.GetDrawer().GetSubmitLabel() != "Reset password" ||
		opened.Msg.GetDrawer().GetItems()[0].GetField().GetName() != "new_password" {
		t.Fatalf("the drawer: %v %v", opened, err)
	}
	save := func(password string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path,
			Values: map[string]string{"new_password": password}}, token))
		if err != nil {
			t.Fatalf("saving: %v", err)
		}
		return answer.Msg
	}
	if weak := save("short"); weak.GetSaved() || weak.GetError() == "" {
		t.Fatalf("a weak password: %+v", weak)
	}
	random := make([]byte, 6)
	_, _ = rand.Read(random)
	if ok := save("Zq" + hex.EncodeToString(random) + "!9Kx"); !ok.GetSaved() {
		t.Fatalf("a strong password: %+v", ok)
	}
	var mustChange bool
	if err := admin.QueryRow(ctx, `SELECT must_change_password FROM "user" WHERE id = $1`, id).Scan(&mustChange); err != nil || !mustChange {
		t.Fatalf("must change %v: %v", mustChange, err)
	}
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, hr)); err != nil ||
		r.Msg.GetRefusal() != "Access Denied: Your active role does not have permission to view Users." {
		t.Fatalf("HR: %v %v", r, err)
	}
}
