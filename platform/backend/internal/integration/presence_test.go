//go:build integration

package integration

import (
	"context"
	"slices"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/presence"
)

// beatRow is what a beat writes on the person's own row.
type beatRow struct {
	seen, since  *time.Time
	path, action string
	login        *string
}

func readBeat(t *testing.T, userID string) beatRow {
	t.Helper()
	var b beatRow
	if err := admin.QueryRow(context.Background(), `
SELECT last_seen_at, online_since, last_seen_path, last_seen_action, last_seen_login_id FROM "user" WHERE id = $1`,
		userID).Scan(&b.seen, &b.since, &b.path, &b.action, &b.login); err != nil {
		t.Fatal(err)
	}
	return b
}

// TestPresenceStampIsTheMiddlewaresBeat stamps as the gateway role, through
// gateway_presence.beat: a post on a page writes the page and action and
// credits the time since the beat before to that beat's slot and sign-in;
// a read, a background request and a bearer's read write nothing; a
// bearer's post moves only the time; nobody else's row changes.
func TestPresenceStampIsTheMiddlewaresBeat(t *testing.T) {
	ctx := context.Background()
	stamper := presence.NewStamper(gateway)
	cceo, ia := snoozer(t, "cceo@edify.org"), snoozer(t, "ia@edify.org")
	before, other := readBeat(t, cceo.UserID), readBeat(t, ia.UserID)
	loginID := "go-integration-" + cuid.New()[:12]
	t.Cleanup(func() {
		c := context.Background()
		_, _ = admin.Exec(c, `UPDATE "user" SET last_seen_at = $2, online_since = $3, last_seen_path = $4,
last_seen_action = $5, last_seen_login_id = $6 WHERE id = $1`,
			cceo.UserID, before.seen, before.since, before.path, before.action, before.login)
		_, _ = admin.Exec(c, `DELETE FROM login_event WHERE id = $1`, loginID)
		_, _ = admin.Exec(c, `DELETE FROM presence_time WHERE user_id = $1 AND section = 'Go Integration'`, cceo.UserID)
	})
	if _, err := admin.Exec(ctx, `INSERT INTO login_event (id, user_id, at, role, user_agent, device, active_seconds, last_active_at)
VALUES ($1, $2, now() - interval '1 hour', 'CCEO', '', '', 5, NULL)`, loginID, cceo.UserID); err != nil {
		t.Fatal(err)
	}
	// The beat before: 100 seconds ago, on a page whose task no seed slot has.
	if _, err := admin.Exec(ctx, `UPDATE "user" SET last_seen_at = now() - interval '100 seconds',
online_since = now() - interval '5 minutes', last_seen_path = '/go-integration', last_seen_action = '',
last_seen_login_id = $2 WHERE id = $1`, cceo.UserID, loginID); err != nil {
		t.Fatal(err)
	}
	slot := func() int {
		t.Helper()
		var seconds int
		err := admin.QueryRow(ctx, `SELECT COALESCE(sum(seconds), 0) FROM presence_time
WHERE user_id = $1 AND section = 'Go Integration' AND working_on = 'Viewing Go Integration'`, cceo.UserID).Scan(&seconds)
		if err != nil {
			t.Fatal(err)
		}
		return seconds
	}

	for _, quiet := range []presence.Request{
		{Method: "GET", Path: "/api/mobile/v1/page", Bearer: true},
		{Method: "GET", Path: "/today/panel", HTMX: true, Background: true},
		{Method: "POST", Path: "/today/snooze", HTMX: true, Background: true},
	} {
		if _, err := stamper.Stamp(ctx, cceo.UserID, quiet); err != nil {
			t.Fatal(err)
		}
	}
	if now := readBeat(t, cceo.UserID); now.path != "/go-integration" || slot() != 0 {
		t.Fatalf("a read or background request stamped: %+v", now)
	}

	credited, err := stamper.Stamp(ctx, cceo.UserID, presence.Request{
		Method: "POST", Path: "/today/snooze", HTMX: true, CurrentURL: "http://localhost/dashboard?x=1",
	})
	if err != nil {
		t.Fatal(err)
	}
	after := readBeat(t, cceo.UserID)
	if credited < 100 || credited > 160 || slot() != credited {
		t.Fatalf("credited %d, slot %d", credited, slot())
	}
	if after.path != "/dashboard" || after.action != "POST /today/snooze" || after.login == nil || *after.login != loginID ||
		after.since == nil {
		t.Fatalf("the beat: %+v", after)
	}
	var active int
	var lastActive time.Time
	if err := admin.QueryRow(ctx, `SELECT active_seconds, last_active_at FROM login_event WHERE id = $1`, loginID).
		Scan(&active, &lastActive); err != nil {
		t.Fatal(err)
	}
	if active != 5+credited || !lastActive.After(after.seen.Add(-time.Duration(credited+1)*time.Second)) {
		t.Fatalf("the sign-in: %d seconds, last active %v", active, lastActive)
	}

	// A second post at once: guarded on the new beat, under a second, so
	// nothing more is credited.
	if credited, err := stamper.Stamp(ctx, cceo.UserID, presence.Request{Method: "POST", Path: "/today/unsnooze", HTMX: true}); err != nil || credited != 0 {
		t.Fatalf("a second post credited %d (%v)", credited, err)
	}
	if again := readBeat(t, cceo.UserID); again.path != "/today/unsnooze" || again.action != "POST /today/unsnooze" {
		t.Fatalf("the second beat: %+v", again)
	}

	// A bearer's post (the app's save): the time moves, the page stays.
	seenBefore := readBeat(t, cceo.UserID).seen
	if credited, err := stamper.Stamp(ctx, cceo.UserID, presence.Request{Method: "POST", Path: "/api/mobile/v1/drawer", Bearer: true}); err != nil || credited != 0 {
		t.Fatalf("a bearer's post credited %d (%v)", credited, err)
	}
	if b := readBeat(t, cceo.UserID); b.path != "/today/unsnooze" || !b.seen.After(*seenBefore) {
		t.Fatalf("a bearer's post: %+v", b)
	}

	if now := readBeat(t, ia.UserID); !sameTime(now.seen, other.seen) || now.path != other.path || now.action != other.action {
		t.Fatalf("someone else's row changed: %+v", now)
	}
}

func sameTime(a, b *time.Time) bool {
	if a == nil || b == nil {
		return a == b
	}
	return a.Equal(*b)
}

// TestThePresenceFunctionIsNarrow: the function's owner holds only the
// columns a beat writes (and the ones its filters read), nothing of whole
// tables; EXECUTE is the presence writer's (which the gateway is a member
// of), never the read-only role's or PUBLIC's; a beat cannot be dated or
// over-credited.
func TestThePresenceFunctionIsNarrow(t *testing.T) {
	ctx := context.Background()
	const fn = "gateway_presence.beat(varchar, varchar, varchar, varchar, timestamptz, varchar, varchar, varchar, varchar, integer, integer, integer, text)"
	var definer bool
	var owner string
	if err := admin.QueryRow(ctx, `
SELECT prosecdef, pg_get_userbyid(proowner) FROM pg_proc WHERE oid = to_regprocedure($1)`, fn).Scan(&definer, &owner); err != nil {
		t.Fatal(err)
	}
	if !definer || owner != "edify_presence_owner" {
		t.Fatalf("security definer %v, owner %q", definer, owner)
	}
	list := func(sql string) []string {
		t.Helper()
		rows, err := admin.Query(ctx, sql)
		if err != nil {
			t.Fatal(err)
		}
		got, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			t.Fatal(err)
		}
		return got
	}
	if tables := list(`SELECT table_name || ':' || privilege_type FROM information_schema.role_table_grants
WHERE grantee = 'edify_presence_owner' ORDER BY 1`); len(tables) != 0 {
		t.Fatalf("the owner holds whole tables: %v", tables)
	}
	writes := list(`SELECT table_name || '.' || column_name || ':' || privilege_type FROM information_schema.column_privileges
WHERE grantee = 'edify_presence_owner' AND privilege_type <> 'SELECT' ORDER BY 1`)
	want := []string{
		"login_event.active_seconds:UPDATE", "login_event.last_active_at:UPDATE",
		"presence_time.day:INSERT", "presence_time.id:INSERT", "presence_time.seconds:INSERT",
		"presence_time.seconds:UPDATE", "presence_time.section:INSERT", "presence_time.user_id:INSERT",
		"presence_time.working_on:INSERT",
		"user.last_seen_action:UPDATE", "user.last_seen_at:UPDATE", "user.last_seen_login_id:UPDATE",
		"user.last_seen_path:UPDATE", "user.online_since:UPDATE",
	}
	if !slices.Equal(writes, want) {
		t.Fatalf("the owner's writes: %v", writes)
	}
	for _, check := range []struct {
		role string
		want bool
	}{
		{"edify_presence_rw", true}, {"edify_gateway", true}, {"edify_gateway_ro", false},
		{"edify_todos_rw", false}, {"public", false},
	} {
		var got bool
		if err := admin.QueryRow(ctx, `SELECT has_function_privilege($1, $2, 'EXECUTE')`, check.role, fn).Scan(&got); err != nil {
			t.Fatal(err)
		}
		if got != check.want {
			t.Errorf("%s EXECUTE: %v, want %v", check.role, got, check.want)
		}
	}
	// Thresholds out of range are refused rather than crediting a day.
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var n int
	if err := tx.QueryRow(ctx, `SELECT gateway_presence.beat('x', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 999999, 30, 600, 'UTC')`).Scan(&n); err == nil {
		t.Fatal("an idle threshold of days was taken")
	}
}
