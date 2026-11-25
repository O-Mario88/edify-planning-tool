//go:build integration

package integration

import (
	"context"
	"net/http"
	"strconv"
	"strings"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// clearExecutionFollowUps removes what the test's own sends wrote: the
// execution follow-ups and their notices with the notices' copies.
func clearExecutionFollowUps(t *testing.T) {
	t.Helper()
	ctx := context.Background()
	notices := `SELECT id FROM notification WHERE context_type = 'PlanningOversightFollowUp'`
	for _, sql := range []string{
		`DELETE FROM outbox_event WHERE event_type = 'notification.email' AND payload->>'deliveryId' IN
			(SELECT id FROM notification_delivery WHERE notification_id IN (` + notices + `))`,
		`DELETE FROM notification_delivery WHERE notification_id IN (` + notices + `)`,
		`DELETE FROM notification WHERE context_type = 'PlanningOversightFollowUp'`,
		`DELETE FROM planning_oversight_follow_up WHERE module IN ('execution', 'planning')`,
	} {
		if _, err := admin.Exec(ctx, sql); err != nil {
			t.Errorf("clearing: %v", err)
		}
	}
}

// Follow Up with PL for execution is Go's: the Director's drawer, a send
// (the follow-up, the Lead's notice and the audit row), and the same send
// again reminding on the open record; anyone else is told it is the
// Director's to send.
func TestCountryExecutionFollowUpIsGos(t *testing.T) {
	ctx := context.Background()
	var lead string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'pl1@edify.org'`).Scan(&lead); err != nil {
		t.Fatalf("the Lead: %v", err)
	}
	clearExecutionFollowUps(t)
	t.Cleanup(func() { clearExecutionFollowUps(t) })
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	path := "/country-planning-oversight/execution/follow-up?view=execution&fy=2026&period=fy&lead=" + lead
	d, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, director))
	if err != nil || d.Msg.GetDrawer().GetTitle() != "Follow Up with PL" {
		t.Fatalf("the drawer: %v %v", d, err)
	}
	due := time.Now().AddDate(0, 0, 7).Format("2006-01-02")
	send := func(instruction string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path, Values: map[string]string{
			"issue": "exec_carryover", "due_date": due, "priority": "high", "instruction": instruction}}, director))
		if err != nil {
			t.Fatalf("sending: %v", err)
		}
		return answer.Msg
	}
	if first := send("Settle the carried work."); !first.GetSaved() || !strings.HasPrefix(first.GetMessage(), "Sent to ") {
		t.Fatalf("the send: %v", first)
	}
	if again := send("Still to settle."); !again.GetSaved() || !strings.HasPrefix(again.GetMessage(), "Reminder 1 sent to ") {
		t.Fatalf("the reminder: %v", again)
	}
	var rows, reminders, notices int
	if err := admin.QueryRow(ctx, `SELECT count(*), max(reminder_count),
		(SELECT count(*) FROM notification WHERE context_type = 'PlanningOversightFollowUp')
		FROM planning_oversight_follow_up WHERE module = 'execution'`).Scan(&rows, &reminders, &notices); err != nil {
		t.Fatal(err)
	}
	if rows != 1 || reminders != 1 || notices != 1 {
		t.Errorf("rows=%d reminders=%d notices=%d", rows, reminders, notices)
	}
	borrowAccount(t, "ia@edify.org")
	ia := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	refused, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, ia))
	if err != nil || !strings.Contains(refused.Msg.GetRefusal(), "belongs to the Country Director") {
		t.Fatalf("Impact Assessment: %v %v", refused, err)
	}
}

// Follow Up with PL on the planning stage is Go's too: the drawer, a send
// about something the Director names (closed by hand) and its reminder.
func TestCountryOversightFollowUpIsGos(t *testing.T) {
	ctx := context.Background()
	var lead string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'pl1@edify.org'`).Scan(&lead); err != nil {
		t.Fatalf("the Lead: %v", err)
	}
	clearExecutionFollowUps(t)
	t.Cleanup(func() { clearExecutionFollowUps(t) })
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	path := "/country-planning-oversight/follow-up?fy=2026&period=fy&lead=" + lead
	d, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, director))
	if err != nil || d.Msg.GetDrawer().GetTitle() != "Follow Up with PL" {
		t.Fatalf("the drawer: %v %v", d, err)
	}
	due := time.Now().AddDate(0, 0, 7).Format("2006-01-02")
	for i, want := range []string{"Sent to ", "Reminder 1 sent to "} {
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path, Values: map[string]string{
			"issue": "other", "due_date": due, "priority": "normal", "instruction": "Settle this " + strconv.Itoa(i)}}, director))
		if err != nil || !answer.Msg.GetSaved() || !strings.HasPrefix(answer.Msg.GetMessage(), want) {
			t.Fatalf("send %d: %v %v", i, answer, err)
		}
	}
	var rows, reminders int
	if err := admin.QueryRow(ctx, `SELECT count(*), max(reminder_count) FROM planning_oversight_follow_up WHERE module = 'planning'`).
		Scan(&rows, &reminders); err != nil {
		t.Fatal(err)
	}
	if rows != 1 || reminders != 1 {
		t.Errorf("rows=%d reminders=%d", rows, reminders)
	}
}
