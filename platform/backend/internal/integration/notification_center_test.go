//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

func notificationCenterOf(token string, request *screensv1.GetNotificationCenterRequest) (*screensv1.GetNotificationCenterResponse, error) {
	answer, err := screensv1connect.NewNotificationCenterServiceClient(http.DefaultClient, baseURL).
		GetNotificationCenter(context.Background(), authed(request, token))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

// fileNotifications gives hr@ a set of notifications and a delivery
// preference of its own, removed when the test ends.
func fileNotifications(t *testing.T) string {
	t.Helper()
	ctx := context.Background()
	hr, pl1 := userIDOf(t, "hr@edify.org"), userIDOf(t, "pl1@edify.org")
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `DELETE FROM notification WHERE id LIKE 'gpn9%'`)
		_, _ = admin.Exec(context.Background(), `DELETE FROM notification_preference WHERE id = 'gpn9pref'`)
	})
	if _, err := admin.Exec(ctx, `DELETE FROM notification WHERE recipient_id = $1`, hr); err != nil {
		t.Fatal(err)
	}
	_, err := admin.Exec(ctx, `
INSERT INTO notification (id, recipient_id, sender_id, title, body, category, context_type, context_id, target_route,
  action_label, action_required, priority, status, created_at, updated_at, resolved_at, reminder_count)
VALUES
 ('gpn901', $1, $2,   '[Go parity check] newest', 'Body', 'follow_up', 'activity', NULL, '/activities/1', NULL, true,
  'urgent', 'unread', '2026-11-02 21:30+00', now(), NULL, 0),
 ('gpn902', $1, NULL, '[Go parity check] read', NULL, 'hr', NULL, NULL, NULL, NULL, false,
  'low', 'read', '2026-11-01 08:00+00', now(), NULL, 0),
 ('gpn903', $1, NULL, '[Go parity check] archived', NULL, 'hr', NULL, NULL, NULL, NULL, false,
  'normal', 'archived', '2026-10-30 08:00+00', now(), NULL, 0),
 ('gpn904', $1, NULL, '[Go parity check] resolved', NULL, 'hr', NULL, NULL, NULL, NULL, true,
  'urgent', 'unread', '2026-10-29 08:00+00', now(), now(), 0)`, hr, pl1)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := admin.Exec(ctx, `
INSERT INTO notification_preference (id, user_id, email_enabled, email_muted_categories, push_enabled, created_at, updated_at)
VALUES ('gpn9pref', $1, false, '["zebra"]', true, now(), now())`, hr); err != nil {
		t.Fatal(err)
	}
	return hr
}

// withholdBodies takes a notice's words away from the gateway's role for one
// test, as before the coordinator's decision (docs/migration/43); roles.sql
// grants them since 2026-11-13.
func withholdBodies(t *testing.T) {
	t.Helper()
	if _, err := admin.Exec(context.Background(), `REVOKE SELECT (body) ON notification FROM edify_gateway_ro`); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `GRANT SELECT (body) ON notification TO edify_gateway_ro`)
	})
}

func TestTheNotificationCentreIsNotAnsweredWithoutANoticesWords(t *testing.T) {
	withholdBodies(t)
	borrowAccount(t, "hr@edify.org")
	token := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	if _, err := notificationCenterOf(token, &screensv1.GetNotificationCenterRequest{}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("the page with the words withheld: %v, want unavailable", err)
	}
}

func TestTheNotificationCentreIsTheReadersOwnAsTheExistingPageDrawsIt(t *testing.T) {
	fileNotifications(t)
	borrowAccount(t, "hr@edify.org")
	token := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()

	page, err := notificationCenterOf(token, &screensv1.GetNotificationCenterRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if k := page.GetKpis(); k.GetActionRequired() != 1 || k.GetCritical() != 1 {
		t.Fatalf("the figures leave out the resolved and the archived: %v", k)
	}
	items := page.GetNotifications()
	if len(items) != 2 || items[0].GetId() != "gpn901" || items[1].GetId() != "gpn902" {
		t.Fatalf("the live ones, newest first: %v", items)
	}
	first := items[0]
	if first.GetPriorityLabel() != "Critical" || first.GetCreatedLabel() != "Nov 3, 2026 00:30" || first.GetSenderName() == "" ||
		first.GetContextId() != "None" || first.GetActionLabel() != "Open Record" || !first.GetActionRequired() {
		t.Fatalf("the newest as the template words it: %v", first)
	}
	if items[1].GetCanMarkRead() || !items[1].GetCanArchive() || items[1].GetTargetRoute() != "" {
		t.Fatalf("a read one: %v", items[1])
	}
	if len(page.GetPageNumbers()) != 0 || page.GetPage().GetTotalPages() != 1 {
		t.Fatalf("one page, no pager: %v %v", page.GetPage(), page.GetPageNumbers())
	}
	d := page.GetDelivery()
	if d.GetEmailEnabled() || !d.GetPushEnabled() || d.GetAddress() != "hr@edify.org" || len(d.GetCategories()) != 3 ||
		d.GetCategories()[2].GetValue() != "zebra" || !d.GetCategories()[2].GetMuted() {
		t.Fatalf("the delivery settings: %v", d)
	}

	archived := "archived"
	only, err := notificationCenterOf(token, &screensv1.GetNotificationCenterRequest{Status: &archived})
	if err != nil || len(only.GetNotifications()) != 1 || only.GetNotifications()[0].GetCanArchive() {
		t.Fatalf("the archived list: %v %v", only, err)
	}
	empty := ""
	none, err := notificationCenterOf(token, &screensv1.GetNotificationCenterRequest{Status: &empty, Q: "parity"})
	if err != nil || len(none.GetNotifications()) != 0 || none.GetFilters().GetStatus() != "" {
		t.Fatalf("an empty status matches nothing: %v %v", none, err)
	}
}

func TestTheNotificationCentreTurnsAwayAClusterLeader(t *testing.T) {
	// The seed of this database has no Cluster Leader: an officer is made
	// one for the test and put back after it.
	email := "cceo19@edify.org"
	restoreAccount(t, email)
	borrowAccount(t, email)
	if _, err := admin.Exec(context.Background(),
		`UPDATE "user" SET roles = ARRAY['ClusterLeader'], active_role = 'ClusterLeader' WHERE email = $1`, email); err != nil {
		t.Fatal(err)
	}
	token := sessionOf(t, email, seededPassword).GetAccessToken()
	if _, err := notificationCenterOf(token, &screensv1.GetNotificationCenterRequest{}); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("a Cluster Leader opening the notification centre: %v, want permission denied", err)
	}
	if _, err := notificationCenterOf("", &screensv1.GetNotificationCenterRequest{}); connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Fatalf("no session: %v, want unauthenticated", err)
	}
}
