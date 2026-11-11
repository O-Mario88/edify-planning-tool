package ownedschema

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// ErrRefused wraps every refusal of a migration run.
var ErrRefused = errors.New("schema: migration refused")

// Conn is what applying migrations needs; *pgx.Conn satisfies it.
type Conn interface {
	Begin(ctx context.Context) (pgx.Tx, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Querier is what reading the applied version needs.
type Querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Applied is one migration a run applied.
type Applied struct {
	Version int
	Name    string
}

// The ledger every Go-owned schema keeps of its applied migrations. %s is
// the schema's own name, checked to be a plain identifier (Spec.check).
const (
	ledgerTable = `CREATE TABLE IF NOT EXISTS %s.schema_migration (
  version integer PRIMARY KEY,
  name text NOT NULL,
  checksum text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
)`
	ledgerRecord = `INSERT INTO %s.schema_migration (version, name, checksum) VALUES ($1, $2, $3)`
)

// Apply brings the schema up to the shipped migrations.
//
// It refuses unless the connected database is the one named in confirm, the
// schema exists and the owner role owns it (platform/deploy/db makes both),
// and every migration already applied still has the checksum it was applied
// with. Each migration runs in its own transaction as the owner role with
// the search path pinned to the schema.
func (s Spec) Apply(ctx context.Context, conn Conn, confirm string) ([]Applied, error) {
	migrations, err := s.Load()
	if err != nil {
		return nil, err
	}
	if err := s.checkTarget(ctx, conn, confirm); err != nil {
		return nil, err
	}
	if err := s.inSchema(ctx, conn, fmt.Sprintf(ledgerTable, s.Name)); err != nil {
		return nil, fmt.Errorf("%s: creating the migration ledger: %w", s.Name, err)
	}

	var applied []Applied
	for _, migration := range migrations {
		done, err := s.applyOne(ctx, conn, migration)
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
func (s Spec) Version(ctx context.Context, q Querier) (int, error) {
	if err := s.check(); err != nil {
		return 0, err
	}
	// Two questions, not one: Postgres plans a subquery on the ledger even
	// when a CASE would never reach it, and fails if the ledger is missing.
	var exists bool
	if err := q.QueryRow(ctx, `SELECT to_regclass($1) IS NOT NULL`, s.Name+".schema_migration").Scan(&exists); err != nil {
		return 0, fmt.Errorf("%s: looking for the migration ledger: %w", s.Name, err)
	}
	if !exists {
		return 0, nil
	}
	var version int
	if err := q.QueryRow(ctx,
		fmt.Sprintf(`SELECT COALESCE(max(version), 0) FROM %s.schema_migration`, s.Name)).Scan(&version); err != nil {
		return 0, fmt.Errorf("%s: reading the applied version: %w", s.Name, err)
	}
	return version, nil
}

// Ready says whether the schema is at the version this build needs.
func (s Spec) Ready(ctx context.Context, q Querier) error {
	applied, err := s.Version(ctx, q)
	if err != nil {
		return err
	}
	if applied < s.Required() {
		return fmt.Errorf("%s is at version %d, this build needs %d: run its migrate command",
			s.Name, applied, s.Required())
	}
	return nil
}

func (s Spec) checkTarget(ctx context.Context, conn Conn, confirm string) error {
	var database, owner string
	err := conn.QueryRow(ctx, `SELECT current_database(),
  COALESCE((SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = $1), '')`, s.Name).
		Scan(&database, &owner)
	if err != nil {
		return fmt.Errorf("%s: reading the target database: %w", s.Name, err)
	}
	if confirm == "" || database != confirm {
		return fmt.Errorf("%w: connected to %q but --confirm-database is %q", ErrRefused, database, confirm)
	}
	if owner != s.OwnerRole {
		return fmt.Errorf("%w: schema %s must exist and be owned by %s (run platform/deploy/db/apply-roles.sh); owner is %q",
			ErrRefused, s.Name, s.OwnerRole, owner)
	}
	return nil
}

// applyOne applies migration unless it is already in the ledger; true when
// it was applied now.
func (s Spec) applyOne(ctx context.Context, conn Conn, migration Migration) (bool, error) {
	tx, err := conn.Begin(ctx)
	if err != nil {
		return false, fmt.Errorf("%s: beginning %s: %w", s.Name, migration.Name, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if err := s.asOwner(ctx, tx); err != nil {
		return false, err
	}
	var recorded string
	err = tx.QueryRow(ctx, fmt.Sprintf(`SELECT checksum FROM %s.schema_migration WHERE version = $1`, s.Name),
		migration.Version).Scan(&recorded)
	switch {
	case err == nil && recorded == migration.Checksum:
		return false, nil
	case err == nil:
		return false, fmt.Errorf("%w: %s was applied with checksum %s and now reads %s; an applied migration is never edited",
			ErrRefused, migration.Name, recorded, migration.Checksum)
	case !errors.Is(err, pgx.ErrNoRows):
		return false, fmt.Errorf("%s: reading the ledger for %s: %w", s.Name, migration.Name, err)
	}

	// No arguments: pgx sends the file as one simple-protocol query, so its
	// statements run in order inside this transaction.
	if _, err := tx.Exec(ctx, migration.SQL); err != nil {
		return false, fmt.Errorf("%s: applying %s: %w", s.Name, migration.Name, err)
	}
	if _, err := tx.Exec(ctx, fmt.Sprintf(ledgerRecord, s.Name),
		migration.Version, migration.Name, migration.Checksum); err != nil {
		return false, fmt.Errorf("%s: recording %s: %w", s.Name, migration.Name, err)
	}
	if err := tx.Commit(ctx); err != nil {
		return false, fmt.Errorf("%s: committing %s: %w", s.Name, migration.Name, err)
	}
	return true, nil
}

func (s Spec) inSchema(ctx context.Context, conn Conn, sql string) error {
	tx, err := conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := s.asOwner(ctx, tx); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, sql); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// asOwner makes the rest of tx run as the schema's owner, inside the schema,
// one run at a time.
func (s Spec) asOwner(ctx context.Context, tx pgx.Tx) error {
	for _, statement := range []string{
		fmt.Sprintf("SELECT pg_advisory_xact_lock(%d)", s.LockKey),
		"SET LOCAL ROLE " + s.OwnerRole,
		"SET LOCAL search_path TO " + s.Name + ", pg_catalog",
		"SET LOCAL lock_timeout = '10s'",
	} {
		if _, err := tx.Exec(ctx, statement); err != nil {
			return fmt.Errorf("%s: preparing the migration session (%s): %w", s.Name, statement, err)
		}
	}
	return nil
}
