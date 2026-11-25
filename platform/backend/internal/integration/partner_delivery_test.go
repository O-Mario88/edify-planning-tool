//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// The Partner names who on its team delivers a piece of its work in Go:
// the drawer offers the team, a name on it is saved and audited, one off it
// is refused in the existing words, and a staff role has no such page.
func TestPartnerNamesWhoDeliversInGo(t *testing.T) {
	ctx := context.Background()
	var partner, activity, status, delivery, assigned, contact string
	if err := admin.QueryRow(ctx, `SELECT p.id, a.id, a.status, COALESCE(a.delivery_type, ''), COALESCE(a.assigned_partner_id, ''),
  COALESCE(a.delivery_contact_name, '')
FROM partner p JOIN "user" u ON u.id = p.user_id, activity a
WHERE u.email = 'partner@edify.org' AND a.deleted_at IS NULL ORDER BY a.id LIMIT 1`).
		Scan(&partner, &activity, &status, &delivery, &assigned, &contact); err != nil {
		t.Fatalf("a piece of work: %v", err)
	}
	restore := func() {
		for _, sql := range []string{
			`DELETE FROM partner_member WHERE id = 'gomember1'`,
			`DELETE FROM audit_log WHERE action = 'partner.delivery_member_named' AND subject_id = '` + activity + `'`,
		} {
			if _, err := admin.Exec(ctx, sql); err != nil {
				t.Errorf("clearing: %v", err)
			}
		}
		if _, err := admin.Exec(ctx, `UPDATE activity SET status = $2, delivery_type = $3, assigned_partner_id = NULLIF($4, ''),
  delivery_contact_name = $5 WHERE id = $1`, activity, status, delivery, assigned, contact); err != nil {
			t.Errorf("restoring the work: %v", err)
		}
	}
	restore()
	t.Cleanup(restore)
	if _, err := admin.Exec(ctx, `UPDATE activity SET status = 'scheduled', delivery_type = 'partner', assigned_partner_id = $2,
  delivery_contact_name = '' WHERE id = $1`, activity, partner); err != nil {
		t.Fatalf("handing the work over: %v", err)
	}
	if _, err := admin.Exec(ctx, `INSERT INTO partner_member (created_at, updated_at, id, name, role, title, phone, email, active, partner_id)
VALUES (now(), now(), 'gomember1', 'Field Officer One', 'officer', '', '', '', true, $1)`, partner); err != nil {
		t.Fatalf("the team: %v", err)
	}
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	path := "/partner/activities/" + activity + "/delivered-by"
	borrowAccount(t, "partner@edify.org")
	login := sessionOf(t, "partner@edify.org", seededPassword).GetAccessToken()
	opened, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, login))
	if err != nil {
		t.Fatalf("opening: %v", err)
	}
	d := opened.Msg.GetDrawer()
	if !d.GetCanSubmit() || d.GetItems()[0].GetText() != "Now: Nobody named yet" || d.GetItems()[1].GetField().GetOptions()[0].GetValue() != "Field Officer One" {
		t.Fatalf("the drawer: %v", d)
	}
	save := func(name string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path,
			Values: map[string]string{"delivery_contact_name": name}}, login))
		if err != nil {
			t.Fatalf("saving %q: %v", name, err)
		}
		return answer.Msg
	}
	if s := save("field officer one"); !s.GetSaved() || s.GetMessage() != "Field Officer One will deliver this work." {
		t.Fatalf("naming the team member: %+v", s)
	}
	var named string
	var audited int
	if err := admin.QueryRow(ctx, `SELECT COALESCE(delivery_contact_name, ''),
  (SELECT count(*) FROM audit_log WHERE action = 'partner.delivery_member_named' AND subject_id = $1) FROM activity WHERE id = $1`, activity).
		Scan(&named, &audited); err != nil || named != "Field Officer One" || audited != 1 {
		t.Fatalf("named %q, audited %d: %v", named, audited, err)
	}
	if s := save("Somebody Else"); s.GetSaved() || s.GetError() != "Somebody Else is not on your organisation's team. Add them under Staff and volunteers on your organisation's profile, then choose them here." {
		t.Fatalf("a name off the team: %+v", s)
	}
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	refused, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, cceo))
	if err != nil || refused.Msg.GetRefusal() != "Access Denied: Your active role does not have permission to view Partner Activities." {
		t.Fatalf("a CCEO: %v %v", refused, err)
	}
}
