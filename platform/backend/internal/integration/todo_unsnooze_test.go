//go:build integration

package integration

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todosnooze"
)

// TestTodoUnsnoozeRemovesOnlyThatPersonsRowForThatTodo undoes a snooze as
// the gateway role, through gateway_todos.unsnooze: the reader's row for the
// To-Do goes; the same To-Do snoozed by someone else, and the reader's other
// snooze, stay; a second undo removes nothing; a reader Go hands on removes
// nothing.
func TestTodoUnsnoozeRemovesOnlyThatPersonsRowForThatTodo(t *testing.T) {
	ctx := context.Background()
	svc, err := todosnooze.NewService(gateway, nil)
	if err != nil {
		t.Fatal(err)
	}
	cceo, ia, cd := snoozer(t, "cceo@edify.org"), snoozer(t, "ia@edify.org"), snoozer(t, "cd@edify.org")
	todoID, otherID := "go-integration-"+cuid.New(), "go-integration-"+cuid.New()
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(),
			`DELETE FROM command_center_todo_snooze WHERE todo_id = ANY($1)`, []string{todoID, otherID})
	})
	for _, made := range []struct{ who, todo string }{
		{cceo.UserID, todoID}, {cceo.UserID, otherID}, {ia.UserID, todoID}, {cd.UserID, todoID},
	} {
		if _, err := admin.Exec(ctx, `
INSERT INTO command_center_todo_snooze (id, created_at, updated_at, user_id, todo_id, title, until)
VALUES ($1, now(), now(), $2, $3, 'Go integration', current_date + 1)`, cuid.New(), made.who, made.todo); err != nil {
			t.Fatal(err)
		}
	}
	left := func() []string {
		t.Helper()
		rows, err := admin.Query(ctx, `
SELECT user_id || '/' || todo_id FROM command_center_todo_snooze WHERE todo_id = ANY($1) ORDER BY 1`,
			[]string{todoID, otherID})
		if err != nil {
			t.Fatal(err)
		}
		got, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			t.Fatal(err)
		}
		return got
	}
	want := func(pairs ...[2]string) []string {
		out := make([]string, 0, len(pairs))
		for _, p := range pairs {
			out = append(out, p[0]+"/"+p[1])
		}
		slices.Sort(out)
		return out
	}

	redraw, err := svc.Unsnooze(ctx, cceo, todosnooze.UnsnoozeRequest{TodoID: todoID})
	if err != nil {
		t.Fatal(err)
	}
	if redraw.Removed != 1 || redraw.Path != "/today/panel" || redraw.Retarget != "[data-dashboard-today]" {
		t.Fatalf("answered %+v", redraw)
	}
	expected := want([2]string{cceo.UserID, otherID}, [2]string{ia.UserID, todoID}, [2]string{cd.UserID, todoID})
	if got := left(); !slices.Equal(got, expected) {
		t.Fatalf("left %v, want %v", got, expected)
	}

	again, err := svc.Unsnooze(ctx, cceo, todosnooze.UnsnoozeRequest{TodoID: todoID})
	if err != nil || again.Removed != 0 {
		t.Fatalf("a second undo: %+v, %v", again, err)
	}
	if _, err := svc.Unsnooze(ctx, cd, todosnooze.UnsnoozeRequest{TodoID: todoID}); !errors.Is(err, todosnooze.ErrHandOn) {
		t.Fatalf("the Country Director (the page refuses): %v", err)
	}
	if got := left(); !slices.Equal(got, expected) {
		t.Fatalf("after a repeat and a hand-on, left %v, want %v", got, expected)
	}

	// No person: the function removes nothing, whatever the To-Do.
	for _, user := range []any{nil, ""} {
		var removed int
		err := pgx.BeginTxFunc(ctx, gateway, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
			return tx.QueryRow(ctx, `SELECT gateway_todos.unsnooze($1, $2)`, user, todoID).Scan(&removed)
		})
		if err != nil || removed != 0 {
			t.Fatalf("no person (%v): removed %d, %v", user, removed, err)
		}
	}
	if got := left(); !slices.Equal(got, expected) {
		t.Fatalf("after an undo with no person, left %v, want %v", got, expected)
	}
}

// TestTheUnsnoozeFunctionIsNarrow holds the function's rights to the
// coordinator's decision: its owner deletes from the snooze table and reads
// only the two columns its filter names, nothing else anywhere; EXECUTE is
// the snooze writer role's alone (and so the gateway's), never the read-only
// role's nor PUBLIC's.
func TestTheUnsnoozeFunctionIsNarrow(t *testing.T) {
	ctx := context.Background()
	const fn = "gateway_todos.unsnooze(varchar, varchar)"
	var definer bool
	var owner string
	if err := admin.QueryRow(ctx, `
SELECT prosecdef, pg_get_userbyid(proowner) FROM pg_proc WHERE oid = to_regprocedure($1)`, fn).Scan(&definer, &owner); err != nil {
		t.Fatal(err)
	}
	if !definer || owner != "edify_todo_unsnooze_owner" {
		t.Fatalf("security definer %v, owner %q", definer, owner)
	}
	rows, err := admin.Query(ctx, `
SELECT table_schema || '.' || table_name || ':' || privilege_type FROM information_schema.role_table_grants
WHERE grantee = 'edify_todo_unsnooze_owner' ORDER BY 1`)
	if err != nil {
		t.Fatal(err)
	}
	tables, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(tables, []string{"public.command_center_todo_snooze:DELETE"}) {
		t.Fatalf("the owner's table rights: %v", tables)
	}
	rows, err = admin.Query(ctx, `
SELECT table_name || '.' || column_name || ':' || privilege_type FROM information_schema.column_privileges
WHERE grantee = 'edify_todo_unsnooze_owner' ORDER BY 1`)
	if err != nil {
		t.Fatal(err)
	}
	columns, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(columns, []string{
		"command_center_todo_snooze.todo_id:SELECT", "command_center_todo_snooze.user_id:SELECT",
	}) {
		t.Fatalf("the owner's column rights: %v", columns)
	}
	for _, check := range []struct {
		role string
		want bool
	}{
		{"edify_todos_rw", true}, {gatewayRole, true}, {"edify_gateway_ro", false}, {"edify_activities_rw", false},
	} {
		var got bool
		if err := admin.QueryRow(ctx, `SELECT has_function_privilege($1, $2, 'EXECUTE')`, check.role, fn).Scan(&got); err != nil {
			t.Fatal(err)
		}
		if got != check.want {
			t.Fatalf("%s may execute: %v, want %v", check.role, got, check.want)
		}
	}
	var public bool
	if err := admin.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM pg_proc, aclexplode(proacl) a WHERE oid = to_regprocedure($1) AND a.grantee = 0)`, fn).Scan(&public); err != nil {
		t.Fatal(err)
	}
	if public {
		t.Fatal("PUBLIC may execute the undo")
	}
}
