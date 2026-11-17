// Package schema owns Edify Global's country registry, the Postgres schema
// country_registry: the countries the platform serves, each country's
// versioned settings, the names the existing tables already use for a
// country, which country each school belongs to, and which countries each
// account may work in (docs/migration/80-multi-country-phase-0.md).
//
// It lives beside the existing application's tables and changes none of
// them: a school's or an account's country is a row here, never a new column
// on the existing table. Its migrations run only through
// `schemactl migrate --schema=country_registry`; the gateway never migrates,
// it asks Ready.
package schema

import (
	"embed"
	"io/fs"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownedschema"
)

// Name is the schema Edify Global owns. Nothing outside it is ever changed.
const Name = "country_registry"

// OwnerRole owns the schema; migrations run as it (SET ROLE). It holds no
// privilege on the existing application's tables (deploy/db/country_roles.sql).
const OwnerRole = "edify_country_owner"

// WriterRole is the only role a migration may grant to.
const WriterRole = "edify_country_rw"

const lockKey = 7_425_031

//go:embed migrations/*.sql
var files embed.FS

// Spec is country_registry as internal/ownedschema describes a schema.
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
