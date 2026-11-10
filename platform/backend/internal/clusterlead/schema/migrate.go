package schema

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// lockKey serialises migration runs (pg_advisory_xact_lock).
const lockKey = 7_425_001

// ErrRefused wraps every refusal of a migration run.
var ErrRefused = errors.New("schema: migration refused")

// Conn is what applying migrations needs; *pgx.Conn satisfies it.
type Conn interface {
	Begin(ctx context.Context) (pgx.Tx, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Applied is one migration a run applied.
type Applied struct {
	Version int
	Name    string
}

// Apply brings cluster_leadership up to the shipped migrations.
//
// It refuses unless the connected database is the one named in confirm, the
// schema exists and edify_cluster_owner owns it (deploy/db/cluster_roles.sql
// makes both), and every migration already applied still has the checksum it
// was applied with. Each migration runs in its own transaction as the owner
// role with the search path pinned to the schema.
func Apply(ctx context.Context, conn Conn, confirm string) ([]Applied, error) {
	migrations, err := Load()
	if err != nil {
		return nil, err
	}
	if err := checkTarget(ctx, conn, confirm); err != nil {
		return nil, err
	}
	if err := inSchema(ctx, conn, `CREATE TABLE IF NOT EXISTS cluster_leadership.schema_migration (
  version integer PRIMARY KEY,
  name text NOT NULL,
  checksum text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
)`); err != nil {
		return nil, fmt.Errorf("schema: creating the migration ledger: %w", err)
	}

	var applied []Applied
	for _, migration := range migrations {
		done, err := applyOne(ctx, conn, migration)
		if err != nil {
			return applied, err
		}
		if done {
			applied = append(applied, Applied{Version: migration.Version, Name: migration.Name})
		}
	}
	return applied, nil
}

// Version is the highest migration applied, or 0 when the schema or its
// ledger is not there. The gateway asks this; it never migrates.
func Version(ctx context.Context, q interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}) (int, error) {
	// Two questions, not one: Postgres plans a subquery on the ledger even
	// when a CASE would never reach it, and fails if the ledger is missing.
	var exists bool
	if err := q.QueryRow(ctx,
		`SELECT to_regclass('cluster_leadership.schema_migration') IS NOT NULL`).Scan(&exists); err != nil {
		return 0, fmt.Errorf("schema: looking for the migration ledger: %w", err)
	}
	if !exists {
		return 0, nil
	}
	var version int
	if err := q.QueryRow(ctx,
		`SELECT COALESCE(max(version), 0) FROM cluster_leadership.schema_migration`).Scan(&version); err != nil {
		return 0, fmt.Errorf("schema: reading the applied version: %w", err)
	}
	return version, nil
}

func checkTarget(ctx context.Context, conn Conn, confirm string) error {
	var database, owner string
	err := conn.QueryRow(ctx, `SELECT current_database(),
  COALESCE((SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = $1), '')`, Name).
		Scan(&database, &owner)
	if err != nil {
		return fmt.Errorf("schema: reading the target database: %w", err)
	}
	if confirm == "" || database != confirm {
		return fmt.Errorf("%w: connected to %q but --confirm-database is %q", ErrRefused, database, confirm)
	}
	if owner != OwnerRole {
		return fmt.Errorf("%w: schema %s must exist and be owned by %s (run platform/deploy/db/apply-roles.sh); owner is %q",
			ErrRefused, Name, OwnerRole, owner)
	}
	return nil
}

// applyOne applies migration unless it is already in the ledger; true when
// it was applied now.
func applyOne(ctx context.Context, conn Conn, migration Migration) (bool, error) {
	tx, err := conn.Begin(ctx)
	if err != nil {
		return false, fmt.Errorf("schema: beginning %s: %w", migration.Name, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if err := asOwner(ctx, tx); err != nil {
		return false, err
	}
	var recorded string
	err = tx.QueryRow(ctx, `SELECT checksum FROM cluster_leadership.schema_migration WHERE version = $1`,
		migration.Version).Scan(&recorded)
	switch {
	case err == nil && recorded == migration.Checksum:
		return false, nil
	case err == nil:
		return false, fmt.Errorf("%w: %s was applied with checksum %s and now reads %s; an applied migration is never edited",
			ErrRefused, migration.Name, recorded, migration.Checksum)
	case !errors.Is(err, pgx.ErrNoRows):
		return false, fmt.Errorf("schema: reading the ledger for %s: %w", migration.Name, err)
	}

	// No arguments: pgx sends the file as one simple-protocol query, so its
	// statements run in order inside this transaction.
	if _, err := tx.Exec(ctx, migration.SQL); err != nil {
		return false, fmt.Errorf("schema: applying %s: %w", migration.Name, err)
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO cluster_leadership.schema_migration (version, name, checksum) VALUES ($1, $2, $3)`,
		migration.Version, migration.Name, migration.Checksum); err != nil {
		return false, fmt.Errorf("schema: recording %s: %w", migration.Name, err)
	}
	if err := tx.Commit(ctx); err != nil {
		return false, fmt.Errorf("schema: committing %s: %w", migration.Name, err)
	}
	return true, nil
}

func inSchema(ctx context.Context, conn Conn, sql string) error {
	tx, err := conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := asOwner(ctx, tx); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, sql); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// asOwner makes the rest of tx run as the schema's owner, inside the schema,
// one run at a time.
func asOwner(ctx context.Context, tx pgx.Tx) error {
	for _, statement := range []string{
		fmt.Sprintf("SELECT pg_advisory_xact_lock(%d)", lockKey),
		"SET LOCAL ROLE " + OwnerRole,
		"SET LOCAL search_path TO " + Name + ", pg_catalog",
		"SET LOCAL lock_timeout = '10s'",
	} {
		if _, err := tx.Exec(ctx, statement); err != nil {
			return fmt.Errorf("schema: preparing the migration session (%s): %w", statement, err)
		}
	}
	return nil
}
