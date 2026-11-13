//go:build integration

package integration

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todosnooze"
)

// snoozer is a seeded account as the gateway loads it.
func snoozer(t *testing.T, email string) auth.Principal {
	t.Helper()
	ctx := context.Background()
	var id string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, email).Scan(&id); err != nil {
		t.Fatalf("seeded account %s: %v", email, err)
	}
	account, err := identity.NewStore(gateway).LoadAccount(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	return auth.Principal{Account: account}
}

type snoozeRow struct {
	id, title, until string
	created, updated time.Time
}

func snoozeOf(t *testing.T, userID, todoID string) (snoozeRow, bool) {
	t.Helper()
	var r snoozeRow
	err := admin.QueryRow(context.Background(), `
SELECT id, title, until::text, created_at, updated_at FROM command_center_todo_snooze
WHERE user_id = $1 AND todo_id = $2`, userID, todoID).Scan(&r.id, &r.title, &r.until, &r.created, &r.updated)
	if err != nil {
		return snoozeRow{}, false
	}
	return r, true
}

// TestTodoSnoozeWritesThroughTheGatewaysOwnRights makes the save as the
// gateway role: a new row, then the same item again (one row, its id and
// created_at kept, the new day and title), a refusal and a hand-on that
// write nothing.
func TestTodoSnoozeWritesThroughTheGatewaysOwnRights(t *testing.T) {
	ctx := context.Background()
	svc, err := todosnooze.NewService(gateway, nil)
	if err != nil {
		t.Fatal(err)
	}
	p := snoozer(t, "cceo@edify.org")
	todoID := "go-integration-" + cuid.New()
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `DELETE FROM command_center_todo_snooze WHERE todo_id = $1`, todoID)
	})

	first, err := svc.Snooze(ctx, p, todosnooze.Request{TodoID: todoID, Choice: "tomorrow", Title: "First"})
	if err != nil {
		t.Fatal(err)
	}
	made, found := snoozeOf(t, p.UserID, todoID)
	if !found || made.title != "First" || made.until != first.Until.Format(time.DateOnly) {
		t.Fatalf("made %+v (found %v), answered %+v", made, found, first)
	}

	second, err := svc.Snooze(ctx, p, todosnooze.Request{TodoID: todoID, Choice: "next_week", Title: "Second"})
	if err != nil {
		t.Fatal(err)
	}
	moved, _ := snoozeOf(t, p.UserID, todoID)
	if moved.id != made.id || !moved.created.Equal(made.created) || moved.title != "Second" ||
		moved.until != second.Until.Format(time.DateOnly) || !moved.updated.After(made.updated) {
		t.Fatalf("updated %+v from %+v", moved, made)
	}
	var rows int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM command_center_todo_snooze WHERE todo_id = $1`, todoID).Scan(&rows); err != nil || rows != 1 {
		t.Fatalf("%d rows (%v)", rows, err)
	}

	var refusal *todosnooze.Refusal
	if _, err := svc.Snooze(ctx, p, todosnooze.Request{TodoID: todoID, Choice: "someday"}); !errors.As(err, &refusal) {
		t.Fatalf("an unknown choice: %v", err)
	}
	cd := snoozer(t, "cd@edify.org")
	if _, err := svc.Snooze(ctx, cd, todosnooze.Request{TodoID: todoID, Choice: "tomorrow"}); !errors.Is(err, todosnooze.ErrHandOn) {
		t.Fatalf("the Country Director (the page refuses): %v", err)
	}
	if _, found := snoozeOf(t, cd.UserID, todoID); found {
		t.Fatal("a handed-on snooze wrote a row")
	}
	after, _ := snoozeOf(t, p.UserID, todoID)
	if after != moved {
		t.Fatalf("a refusal changed the row: %+v", after)
	}
}
