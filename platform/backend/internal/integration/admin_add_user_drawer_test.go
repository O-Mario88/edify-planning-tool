//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// The Users page's Add User drawer and its save are Go's: the Admin's drawer
// offers the supervisors and districts; a post without a name is refused in
// Django's words; a full one creates the invited account with its staff
// profile, districts and supervisor in one go; a taken email is refused;
// HR has no Users page.
func TestAdminAddsAUserInGo(t *testing.T) {
	ctx := context.Background()
	const email = "go.add.user@edify.test"
	removeCreated(t, email)
	t.Cleanup(func() {
		// Runs before removeCreated's cleanup: the supervisor link holds the
		// staff profile.
		_, _ = admin.Exec(ctx, `DELETE FROM staff_supervisor_assignment WHERE supervisee_id IN
  (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = $1)`, email)
	})
	var supervisor, district string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.active_role = 'Program Lead' AND sp.deleted_at IS NULL AND u.deleted_at IS NULL ORDER BY u.name LIMIT 1`).Scan(&supervisor); err != nil {
		t.Fatalf("a Program Lead: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT id FROM district ORDER BY name LIMIT 1`).Scan(&district); err != nil {
		t.Fatalf("a district: %v", err)
	}
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	const path = "/admin-panel/users?drawer=add"
	borrowAccount(t, "admin@edify.org")
	token := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	opened, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, token))
	if err != nil || opened.Msg.GetDrawer().GetSubmitLabel() != "Add user" {
		t.Fatalf("the drawer: %v %v", opened, err)
	}
	offered := false
	for _, item := range opened.Msg.GetDrawer().GetItems() {
		if item.GetField().GetName() == "supervisor_staff_id" {
			for _, o := range item.GetField().GetOptions() {
				offered = offered || o.GetValue() == supervisor
			}
		}
	}
	if !offered {
		t.Fatalf("the Program Lead is not offered as a supervisor")
	}
	save := func(values map[string]string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path, Values: values}, token))
		if err != nil {
			t.Fatalf("saving: %v", err)
		}
		return answer.Msg
	}
	if r := save(map[string]string{"email": email, "role": "CCEO"}); r.GetSaved() ||
		r.GetError() != "Name, email, and primary role are required." {
		t.Fatalf("no name: %+v", r)
	}
	full := map[string]string{"name": "Go Test " + email, "email": email, "role": "CCEO",
		"supervisor_staff_id": supervisor, "primary_district": district}
	if r := save(full); !r.GetSaved() ||
		r.GetMessage() != "User 'Go Test "+email+"' created. An invitation to set their own password was sent." {
		t.Fatalf("the account: %+v", r)
	}
	var status, linked string
	var districts int
	if err := admin.QueryRow(ctx, `SELECT u.status, COALESCE((SELECT a.supervisor_id FROM staff_supervisor_assignment a WHERE a.supervisee_id = sp.id), ''),
  (SELECT count(*) FROM staff_geography_assignment g WHERE g.staff_id = sp.id)
FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id WHERE u.email = $1`, email).Scan(&status, &linked, &districts); err != nil {
		t.Fatalf("the stored account: %v", err)
	}
	if status != "pending_invited" || linked != supervisor || districts != 1 {
		t.Fatalf("stored status %q supervisor %q districts %d", status, linked, districts)
	}
	if r := save(full); r.GetSaved() || r.GetError() != "A user with this email already exists." {
		t.Fatalf("a taken email: %+v", r)
	}
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, hr)); err != nil ||
		r.Msg.GetRefusal() != "Access Denied: Your active role does not have permission to view Users." {
		t.Fatalf("HR: %v %v", r, err)
	}
}
