// Package schema owns the Smart Route Planner's Postgres schema,
// field_routes: reports that a school's location is wrong or missing, the
// review of each, and the locations reviewers have verified. Its migrations
// run only through `schemactl migrate --schema=field_routes`; the mechanics
// (lint, checksums, the ledger, running as the owner role) are
// internal/ownedschema's. The gateway never migrates: it asks Ready.
//
// The existing application's school coordinates (school.latitude/longitude,
// school_geo_point) are never written: a verified location lives here and
// the planner reads it first.
package schema

import (
	"embed"
	"io/fs"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownedschema"
)

// Name is the schema the planner owns. Nothing outside it is ever changed.
const Name = "field_routes"

// OwnerRole owns the schema; migrations run as it (SET ROLE). It holds no
// privilege on the existing application's tables (deploy/db/routes_roles.sql).
const OwnerRole = "edify_routes_owner"

// WriterRole is the only role a migration may grant to.
const WriterRole = "edify_routes_rw"

const lockKey = 7_425_017

//go:embed migrations/*.sql
var files embed.FS

// Spec is field_routes as internal/ownedschema describes a schema.
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
		panic(err) // embedded at build time
	}
	return sub
}
