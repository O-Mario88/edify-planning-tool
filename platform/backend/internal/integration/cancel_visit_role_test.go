//go:build integration

package integration

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// The third save, cancelling a visit (docs/migration/30, the owner's
// decision 30.4): the gateway withdraws the visit's unmoved advances only
// through gateway_money.withdraw_unmoved_advances, inside its own
// transaction. The function removes exactly that activity's advances whose
// money has not moved; a moved one and another activity's stay. The gateway
// can neither delete an advance itself nor become the function's owner
// (TestGatewayRoleCanNeitherWriteNorReadSecrets says so too). Everything the
// gateway does here is rolled back; the one advance the test marks moved is
// put back.
func TestTheWithdrawFunctionRemovesOnlyThatActivitysUnmovedAdvances(t *testing.T) {
	ctx := context.Background()
	var target, other string
	if err := admin.QueryRow(ctx, `SELECT activity_id FROM advance_request
GROUP BY activity_id HAVING count(*) >= 2 ORDER BY activity_id LIMIT 1`).Scan(&target); err != nil {
		t.Skipf("the test database has no activity with two advances (%v)", err)
	}
	if err := admin.QueryRow(ctx, `SELECT activity_id FROM advance_request WHERE activity_id <> $1
ORDER BY activity_id LIMIT 1`, target).Scan(&other); err != nil {
		t.Fatal(err)
	}
	// One of the visit's advances has its money moved for the test, and is
	// put back as it was afterwards.
	var moved, was string
	if err := admin.QueryRow(ctx, `SELECT id, status FROM advance_request WHERE activity_id = $1
ORDER BY id LIMIT 1`, target).Scan(&moved, &was); err != nil {
		t.Fatal(err)
	}
	if _, err := admin.Exec(ctx, `UPDATE advance_request SET status = 'disbursed' WHERE id = $1`, moved); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `UPDATE advance_request SET status = $2 WHERE id = $1`, moved, was)
	})

	ids := func(activity string, unmoved bool) []string {
		rows, err := admin.Query(ctx, `SELECT id FROM advance_request WHERE activity_id = $1
  AND (status <> 'disbursed') = $2 ORDER BY id`, activity, unmoved)
		if err != nil {
			t.Fatal(err)
		}
		found, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			t.Fatal(err)
		}
		return found
	}
	unmoved, others := ids(target, true), ids(other, true)
	if len(unmoved) == 0 || len(others) == 0 {
		t.Skip("the test database has no unmoved advances to withdraw")
	}

	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var removed int
	if err := tx.QueryRow(ctx, `SELECT gateway_money.withdraw_unmoved_advances($1)`, target).Scan(&removed); err != nil {
		t.Fatalf("the gateway's withdrawal: %v", err)
	}
	if removed != len(unmoved) {
		t.Fatalf("removed %d advances, want the activity's %d unmoved ones", removed, len(unmoved))
	}
	asked := append(append(append([]string{}, unmoved...), moved), others...)
	rows, err := tx.Query(ctx, `SELECT id FROM advance_request WHERE id = ANY($1) ORDER BY id`, asked)
	if err != nil {
		t.Fatal(err)
	}
	left, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatal(err)
	}
	want := append([]string{moved}, others...)
	slices.Sort(want)
	if !slices.Equal(left, want) {
		t.Fatalf("left %v, want the moved advance and the other activity's %v", left, want)
	}
	_ = tx.Rollback(ctx)

	for name, statement := range map[string]string{
		"delete an advance itself": `DELETE FROM advance_request WHERE activity_id = '` + target + `'`,
		"become the owner role":    `SET ROLE edify_advance_withdraw_owner`,
	} {
		conn, err := gateway.Acquire(ctx)
		if err != nil {
			t.Fatal(err)
		}
		_, err = conn.Conn().PgConn().Exec(ctx, `BEGIN READ WRITE; `+statement).ReadAll()
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "42501" {
			t.Fatalf("%s: must be refused for privilege, got %v", name, err)
		}
		_, _ = conn.Conn().PgConn().Exec(ctx, "ROLLBACK").ReadAll()
		conn.Release()
	}
}
