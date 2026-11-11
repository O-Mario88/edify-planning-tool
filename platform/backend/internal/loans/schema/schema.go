// Package schema owns the School Loan Application Portal's Postgres schema,
// school_loans, and its migrations. They are applied only by
// `schemactl migrate --schema=school_loans`; the gateway checks the version
// and never migrates.
package schema

import (
	"embed"
	"io/fs"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownedschema"
)

// Name is the schema the portal owns. Nothing outside it is ever changed.
const Name = "school_loans"

//go:embed migrations/*.sql
var files embed.FS

// Spec is school_loans as internal/ownedschema describes a schema. Its owner
// holds no privilege on the existing application's tables
// (platform/deploy/db/loan_roles.sql).
var Spec = ownedschema.Spec{
	Name:       Name,
	OwnerRole:  "edify_loans_owner",
	WriterRole: "edify_loans_rw",
	Files:      mustSub(files, "migrations"),
	LockKey:    7_425_002,
}

func mustSub(root fs.FS, dir string) fs.FS {
	sub, err := fs.Sub(root, dir)
	if err != nil {
		panic(err) // the directory is embedded at build time
	}
	return sub
}
