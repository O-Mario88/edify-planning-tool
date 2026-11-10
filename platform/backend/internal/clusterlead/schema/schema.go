// Package schema owns the Cluster Leader Portal's Postgres schema,
// cluster_leadership: its migrations, the lint every migration must pass,
// and the one command path that applies them (cmd/clusterctl migrate).
//
// The gateway never migrates: it only asks Version whether the schema it
// needs is there (brief: "Disable automatic database migrations in all
// application startup paths").
package schema

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"fmt"
	"io/fs"
	"path"
	"sort"
	"strconv"
	"strings"
)

// Name is the schema the portal owns. Nothing outside it is ever changed.
const Name = "cluster_leadership"

// OwnerRole owns the schema; migrations run as it (SET ROLE). It holds no
// privilege on the existing application's tables (deploy/db/cluster_roles.sql).
const OwnerRole = "edify_cluster_owner"

// WriterRole is the only role a migration may grant to.
const WriterRole = "edify_cluster_rw"

//go:embed migrations/*.sql
var files embed.FS

// Migration is one numbered file of migrations/.
type Migration struct {
	Version  int
	Name     string
	SQL      string
	Checksum string
}

// Load returns the shipped migrations in order, each linted, numbered from 1
// without gaps.
func Load() ([]Migration, error) {
	names, err := fs.Glob(files, "migrations/*.sql")
	if err != nil {
		return nil, fmt.Errorf("schema: listing migrations: %w", err)
	}
	sort.Strings(names)
	migrations := make([]Migration, 0, len(names))
	for index, name := range names {
		raw, err := files.ReadFile(name)
		if err != nil {
			return nil, fmt.Errorf("schema: reading %s: %w", name, err)
		}
		base := path.Base(name)
		number, _, found := strings.Cut(base, "_")
		version, err := strconv.Atoi(number)
		if !found || err != nil {
			return nil, fmt.Errorf("schema: %s must be named NNNN_name.sql", base)
		}
		if version != index+1 {
			return nil, fmt.Errorf("schema: %s is version %d, want %d", base, version, index+1)
		}
		if err := Lint(string(raw)); err != nil {
			return nil, fmt.Errorf("schema: %s: %w", base, err)
		}
		sum := sha256.Sum256(raw)
		migrations = append(migrations, Migration{
			Version:  version,
			Name:     strings.TrimSuffix(base, ".sql"),
			SQL:      string(raw),
			Checksum: hex.EncodeToString(sum[:]),
		})
	}
	return migrations, nil
}

// Required is the version the code in this build needs.
func Required() int {
	migrations, err := Load()
	if err != nil || len(migrations) == 0 {
		return 0
	}
	return migrations[len(migrations)-1].Version
}
