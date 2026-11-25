//go:build integration

package integration

import (
	"context"
	"net/http"
	"strings"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// Partner Oversight's hand-over send is Go's: a hand-over the Partner
// returned is sent to its managing CCEO as a TeamAction, with the CCEO's
// notice, the school's system message and the audit row; the same send
// again is refused; a role without the page cannot save the drawer.
func TestPartnerOversightSendIsGos(t *testing.T) {
	ctx := context.Background()
	var id, before, monitor, cceoUser string
	if err := admin.QueryRow(ctx, `SELECT pa.id, pa.status, COALESCE(pa.monitoring_staff_id, ''), sp.id, sp.user_id
FROM partner_assignment pa, staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND pa.school_id IS NOT NULL
  AND (pa.project_id IS NULL OR COALESCE(pa.focus_intervention, '') <> '') ORDER BY pa.id LIMIT 1`).
		Scan(&id, &before, &monitor, new(string), &cceoUser); err != nil {
		t.Fatalf("a hand-over: %v", err)
	}
	restore := func() {
		for _, sql := range []string{
			`DELETE FROM notification WHERE context_type IN ('TeamAction', 'Message') AND recipient_id = '` + cceoUser + `'
  AND created_at > now() - interval '1 hour'`,
			`DELETE FROM team_action WHERE condition_key = 'partner_oversight|assignment_returned|assignment|` + id + `'`,
		} {
			if _, err := admin.Exec(ctx, sql); err != nil {
				t.Errorf("clearing: %v", err)
			}
		}
		if _, err := admin.Exec(ctx, `UPDATE partner_assignment SET status = $2, monitoring_staff_id = NULLIF($3, ''),
  return_reason = '' WHERE id = $1`, id, before, monitor); err != nil {
			t.Errorf("restoring the hand-over: %v", err)
		}
	}
	restore()
	t.Cleanup(restore)
	if _, err := admin.Exec(ctx, `UPDATE partner_assignment SET status = 'returned_to_staff', return_reason = 'The school is closed',
  monitoring_staff_id = (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'cceo@edify.org')
WHERE id = $1`, id); err != nil {
		t.Fatalf("returning the hand-over: %v", err)
	}
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	save := func(token, note string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{
			Path: "/partner-oversight/detail?assignment_id=" + id, Values: map[string]string{"note": note}}, token))
		if err != nil {
			t.Fatalf("saving: %v", err)
		}
		return answer.Msg
	}
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	sent := save(lead, "Please decide this week")
	if !sent.GetSaved() || !strings.HasPrefix(sent.GetMessage(), "Sent to ") || !strings.HasSuffix(sent.GetMessage(), ". Tracked under Actions Sent.") {
		t.Fatalf("the send: %+v", sent)
	}
	var state, recipient, message string
	if err := admin.QueryRow(ctx, `SELECT state, recipient_id, message FROM team_action
WHERE condition_key = 'partner_oversight|assignment_returned|assignment|' || $1`, id).Scan(&state, &recipient, &message); err != nil ||
		state != "open" || recipient != cceoUser || message != "Please decide this week" {
		t.Fatalf("the action %q to %q (%q): %v", state, recipient, message, err)
	}
	var assigned, chats, audited int
	if err := admin.QueryRow(ctx, `SELECT
  (SELECT count(*) FROM notification WHERE recipient_id = $1 AND source_event_type = 'school_action_assigned'
     AND context_id = (SELECT id FROM team_action WHERE condition_key = 'partner_oversight|assignment_returned|assignment|' || $2)),
  (SELECT count(*) FROM notification n JOIN message m ON m.id = n.context_id WHERE n.recipient_id = $1 AND n.source_event_type = 'message'
     AND m.is_system_generated AND m.body LIKE '%Please decide this week'),
  (SELECT count(*) FROM audit_log WHERE action = 'school_action.sent' AND subject_id =
     (SELECT id FROM team_action WHERE condition_key = 'partner_oversight|assignment_returned|assignment|' || $2))`, cceoUser, id).
		Scan(&assigned, &chats, &audited); err != nil || assigned != 1 || chats != 1 || audited != 1 {
		t.Fatalf("notice %d, message %d, audit %d: %v", assigned, chats, audited, err)
	}
	if again := save(lead, ""); again.GetSaved() || !strings.HasPrefix(again.GetError(), "Already sent to ") {
		t.Fatalf("the same send again: %+v", again)
	}
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	if nope := save(hr, ""); nope.GetSaved() || nope.GetError() != "This drawer is not available." {
		t.Fatalf("HR: %+v", nope)
	}
}
