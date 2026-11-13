//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	"connectrpc.com/connect"

	messagingv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1/messagingv1connect"
)

func inboxOf(t *testing.T, token string, request *messagingv1.ListThreadsRequest) *messagingv1.ListThreadsResponse {
	t.Helper()
	answer, err := messagingv1connect.NewMessagingServiceClient(http.DefaultClient, baseURL).ListThreads(context.Background(), authed(request, token))
	if err != nil {
		t.Fatalf("the inbox: %v", err)
	}
	return answer.Msg
}

func unreadOf(t *testing.T, token string) int32 {
	t.Helper()
	answer, err := messagingv1connect.NewMessagingServiceClient(http.DefaultClient, baseURL).GetUnreadCount(context.Background(),
		authed(&messagingv1.GetUnreadCountRequest{}, token))
	if err != nil {
		t.Fatalf("the unread count: %v", err)
	}
	return answer.Msg.GetUnread()
}

// seedThread files a thread from one account to another with one message,
// removed when the test ends.
func seedThread(t *testing.T, id, contextType, contextID, from, to string) {
	t.Helper()
	ctx := context.Background()
	t.Cleanup(func() {
		for _, s := range []string{`DELETE FROM message WHERE thread_id = $1`, `DELETE FROM messaging_messageparticipant WHERE thread_id = $1`,
			`DELETE FROM messaging_messagethread WHERE id = $1`} {
			if _, err := admin.Exec(context.Background(), s, id); err != nil {
				t.Errorf("removing thread %s: %v", id, err)
			}
		}
	})
	steps := []struct {
		sql  string
		args []any
	}{
		{`INSERT INTO messaging_messagethread (id, created_at, updated_at, subject, context_type, context_id, context_label, priority,
  created_by, last_reply_at, is_system_generated, linked_items)
 VALUES ($1, now(), now(), $5, NULLIF($2::text, ''), NULLIF($3::text, ''), 'A record', 'high', $4, now(), false, '[]')`,
			[]any{id, contextType, contextID, from, "Integration " + id}},
		{`INSERT INTO messaging_messageparticipant (id, created_at, updated_at, thread_id, user_id, recipient_type, starred)
 VALUES ($4, now(), now(), $1, $2, 'to', false), ($5, now(), now(), $1, $3, 'to', false)`,
			[]any{id, from, to, id + "a", id + "b"}},
		{`INSERT INTO message (id, created_at, updated_at, thread_id, sender_id, recipient_id, body, priority, action_required,
  is_system_generated, status)
 VALUES ($4, now(), now(), $1, $2, $3, 'Hello from the integration test', 'high', false, false, 'unread')`,
			[]any{id, from, to, id + "m"}},
	}
	for _, step := range steps {
		if _, err := admin.Exec(ctx, step.sql, step.args...); err != nil {
			t.Fatalf("seeding thread %s: %v", id, err)
		}
	}
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheInboxListsAThreadUnreadForItsRecipientOnly(t *testing.T) {
	ctx := context.Background()
	var officer, lead string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'cceo@edify.org'`).Scan(&officer); err != nil {
		t.Fatal(err)
	}
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'pl1@edify.org'`).Scan(&lead); err != nil {
		t.Fatal(err)
	}
	seedThread(t, "itmsgsystem0001", "system", "sys-it", lead, officer)
	seedThread(t, "itmsgnoctx00001", "", "", lead, officer)
	borrowAccount(t, "cceo@edify.org")
	borrowAccount(t, "pl1@edify.org")
	officerToken := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	leadToken := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()

	inbox := inboxOf(t, officerToken, &messagingv1.ListThreadsRequest{})
	var found *messagingv1.ThreadRow
	for _, row := range inbox.GetThreads() {
		if row.GetId() == "itmsgnoctx00001" {
			t.Fatal("a thread with no record is listed")
		}
		if row.GetId() == "itmsgsystem0001" {
			found = row
		}
	}
	if found == nil {
		t.Fatalf("the officer's inbox lacks the thread: %v", inbox.GetThreads())
	}
	if !found.GetUnread() || found.GetContextBadge() != "System Issue" || found.GetPriorityBadge() != "High" ||
		found.GetSnippet() != "Hello from the integration test" || found.GetInitials() == "" {
		t.Fatalf("the officer's row: %v", found)
	}
	if inbox.GetTitle() != "Messages" || len(inbox.GetTabs()) != 8 || inbox.GetTabs()[1].GetCount() < 1 {
		t.Fatalf("the inbox: %v", inbox.GetTabs())
	}
	if unreadOf(t, officerToken) < 1 {
		t.Fatal("the officer's badge counts nothing")
	}
	for _, row := range inboxOf(t, leadToken, &messagingv1.ListThreadsRequest{Tab: "sent"}).GetThreads() {
		if row.GetId() == "itmsgsystem0001" && row.GetUnread() {
			t.Fatal("the sender's own message is unread for them")
		}
	}
	// Opening is the existing application's: reading the list wrote nothing.
	var read int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM messaging_messageparticipant WHERE thread_id = 'itmsgsystem0001' AND last_read_at IS NOT NULL`).Scan(&read); err != nil || read != 0 {
		t.Fatalf("read cursors moved: %d %v", read, err)
	}
	if _, err := messagingv1connect.NewMessagingServiceClient(http.DefaultClient, baseURL).ListThreads(ctx,
		connect.NewRequest(&messagingv1.ListThreadsRequest{})); connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Fatalf("without a session: %v", err)
	}
}
