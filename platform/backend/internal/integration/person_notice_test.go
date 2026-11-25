//go:build integration

package integration

import (
	"context"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

// notify_from_person in Go, as the gateway role: a person's notice is
// written once, sending it again reminds on it (the count and the sender
// kept), and each send queues its email copy. Rolled back.
func TestNotifyFromPersonWritesThenReminds(t *testing.T) {
	ctx := context.Background()
	var lead, director string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM "user" WHERE email = 'pl1@edify.org'), (SELECT id FROM "user" WHERE email = 'cd@edify.org')`).Scan(&lead, &director); err != nil {
		t.Fatalf("the people: %v", err)
	}
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatalf("opening: %v", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	now := time.Now()
	notice := activities.PersonNotice{Recipient: lead, ContextType: "PlanningOversightFollowUp", ContextID: "gpnotice1",
		Event: "planning_followup_assigned", Sender: director, Fields: map[string]any{"recipient_role": "Program Lead",
			"title": "Follow up", "body": "First", "category": "planning", "action_required": true, "priority": "high",
			"status": "unread", "read_at": nil, "resolved_at": nil}}
	first, created, err := activities.NotifyFromPerson(ctx, tx, nil, now, notice)
	if err != nil || !created {
		t.Fatalf("the first send: %v created=%v", err, created)
	}
	notice.Fields = map[string]any{"title": "Reminder: Follow up", "body": "Again", "status": "unread", "read_at": nil}
	again, created, err := activities.NotifyFromPerson(ctx, tx, nil, now.Add(time.Minute), notice)
	if err != nil || created || again != first {
		t.Fatalf("the reminder: %v created=%v %s %s", err, created, again, first)
	}
	var title, body, sender, priority string
	var reminders, emails int
	if err := tx.QueryRow(ctx, `SELECT n.title, n.body, n.sender_id, n.priority, n.reminder_count,
		(SELECT count(*) FROM notification_delivery d WHERE d.notification_id = n.id AND d.channel = 'email')
		FROM notification n WHERE n.id = $1`, first).Scan(&title, &body, &sender, &priority, &reminders, &emails); err != nil {
		t.Fatalf("reading it back: %v", err)
	}
	if title != "Reminder: Follow up" || body != "Again" || sender != director || priority != "high" || reminders != 1 || emails != 2 {
		t.Errorf("notice %q %q %q %q reminders=%d emails=%d", title, body, sender, priority, reminders, emails)
	}
}
