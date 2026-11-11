// Package schema owns the Cluster Leader Portal's Postgres schema,
// cluster_leadership: its migrations, and the one command path that applies
// them (cmd/clusterctl migrate). The mechanics — lint, checksums, the
// migration ledger, running as the owner role — are internal/ownedschema's.
//
// The gateway never migrates: it only asks Version whether the schema it
// needs is there (brief: "Disable automatic database migrations in all
// application startup paths").
package schema

import (
	"context"
	"embed"
	"io/fs"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownedschema"
)

// Name is the schema the portal owns. Nothing outside it is ever changed.
const Name = "cluster_leadership"

// OwnerRole owns the schema; migrations run as it (SET ROLE). It holds no
// privilege on the existing application's tables (deploy/db/cluster_roles.sql).
const OwnerRole = "edify_cluster_owner"

// WriterRole is the only role a migration may grant to.
const WriterRole = "edify_cluster_rw"

// lockKey serialises migration runs (pg_advisory_xact_lock).
const lockKey = 7_425_001

//go:embed migrations/*.sql
var files embed.FS

// Spec is cluster_leadership as internal/ownedschema describes a schema.
var Spec = ownedschema.Spec{
	Name:       Name,
	OwnerRole:  OwnerRole,
	WriterRole: WriterRole,
	Files:      mustSub(files, "migrations"),
	LockKey:    lockKey,
}

func mustSub(root fs.FS, dir string) fs.FS {
	sub, err := fs.Sub(root, dir)
	if err != nil {
		panic(err) // the directory is embedded at build time
	}
	return sub
}

// Migration, Applied, Conn and ErrRefused are ownedschema's.
type (
	Migration = ownedschema.Migration
	Applied   = ownedschema.Applied
	Conn      = ownedschema.Conn
)

// ErrRefused wraps every refusal of a migration run.
var ErrRefused = ownedschema.ErrRefused

// Load returns the shipped migrations in order, each linted.
func Load() ([]Migration, error) { return Spec.Load() }

// Required is the version the code in this build needs.
func Required() int { return Spec.Required() }

// Lint refuses SQL that reaches outside cluster_leadership.
func Lint(sql string) error { return Spec.Lint(sql) }

// Apply brings cluster_leadership up to the shipped migrations.
func Apply(ctx context.Context, conn Conn, confirm string) ([]Applied, error) {
	return Spec.Apply(ctx, conn, confirm)
}

// Version is the highest migration applied, or 0 when there is none.
func Version(ctx context.Context, q ownedschema.Querier) (int, error) {
	return Spec.Version(ctx, q)
}
