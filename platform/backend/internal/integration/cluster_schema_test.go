//go:build integration

package integration

import (
	"context"
	"errors"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead/schema"
)

// The Cluster Leader Portal's schema is Go-owned and walled off from the
// existing application's tables twice: by the lint every migration passes,
// and by the owner role holding no privilege on them. These tests prove the
// second wall and the gateway's narrow write grants on a real database.

func TestClusterSchemaIsMigratedOnceAndToThisBuild(t *testing.T) {
	ctx := context.Background()
	conn, err := admin.Acquire(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Release()

	applied, err := schema.Apply(ctx, conn.Conn(), conn.Conn().Config().Database)
	if err != nil {
		t.Fatalf("a second run must be a no-op, got %v", err)
	}
	if len(applied) != 0 {
		t.Fatalf("a second run applied %v", applied)
	}
	if version, err := schema.Version(ctx, gateway); err != nil || version != schema.Required() {
		t.Fatalf("the gateway reads version %d (%v), the build needs %d", version, err, schema.Required())
	}
	if _, err := schema.Apply(ctx, conn.Conn(), "edify_pm"); !errors.Is(err, schema.ErrRefused) {
		t.Fatalf("a run confirmed for another database must be refused, got %v", err)
	}
}

func TestClusterOwnerCannotTouchTheExistingTables(t *testing.T) {
	statements := map[string]string{
		"alter an existing table": `ALTER TABLE school ADD COLUMN owner_should_not_exist int`,
		"index an existing table": `CREATE INDEX owner_should_not_exist ON school (name)`,
		"read an existing table":  `SELECT 1 FROM school LIMIT 1`,
		"create in public":        `CREATE TABLE public.owner_should_not_exist (id int)`,
		"write an existing table": `UPDATE region SET name = name`,
	}
	for name, statement := range statements {
		t.Run(name, func(t *testing.T) {
			ctx := context.Background()
			tx, err := admin.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = tx.Rollback(ctx) }()
			if _, err := tx.Exec(ctx, "SET LOCAL ROLE "+schema.OwnerRole); err != nil {
				t.Fatal(err)
			}
			_, err = tx.Exec(ctx, statement)
			requireRefused(t, err)
		})
	}
}

func TestGatewayWritesOnlyThePortalsOwnTables(t *testing.T) {
	ctx := context.Background()
	t.Run("a leader assignment, in a read-write transaction", func(t *testing.T) {
		tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = tx.Rollback(ctx) }()
		_, err = tx.Exec(ctx, `INSERT INTO cluster_leadership.leader_assignment
  (id, cluster_id, user_id, starts_on, status, assigned_by)
  VALUES (gen_random_uuid(), 'c1', 'u1', current_date, 'active', 'u0')`)
		if err != nil {
			t.Fatalf("the gateway must be able to record an assignment: %v", err)
		}
	})

	refused := map[string]string{
		"without a read-write transaction": `INSERT INTO cluster_leadership.assignment_event (assignment_id, event, actor_id) VALUES (gen_random_uuid(), 'assigned', 'u0')`,
		"delete an assignment":             `DELETE FROM cluster_leadership.leader_assignment`,
		"rewrite an event":                 `UPDATE cluster_leadership.assignment_event SET reason = 'x'`,
		"delete an event":                  `DELETE FROM cluster_leadership.assignment_event`,
		"change the ledger":                `INSERT INTO cluster_leadership.schema_migration (version, name, checksum) VALUES (99, 'x', 'x')`,
		"create in the portal's schema":    `CREATE TABLE cluster_leadership.gateway_should_not_exist (id int)`,
		"update a school even read-write":  `UPDATE school SET name = name`,
	}
	for name, statement := range refused {
		t.Run(name, func(t *testing.T) {
			mode := pgx.ReadWrite
			if name == "without a read-write transaction" {
				mode = pgx.ReadOnly
			}
			tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: mode})
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = tx.Rollback(ctx) }()
			_, err = tx.Exec(ctx, statement)
			requireRefused(t, err)
		})
	}
}

func requireRefused(t *testing.T, err error) {
	t.Helper()
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) {
		t.Fatalf("the statement was not refused (err=%v)", err)
	}
	// 42501 insufficient_privilege, 25006 read_only_sql_transaction
	if pgErr.Code != "42501" && pgErr.Code != "25006" {
		t.Fatalf("refused for an unexpected reason: %s %s", pgErr.Code, pgErr.Message)
	}
}
