// Package ownedschema owns the mechanics shared by every Go-owned Postgres
// schema: numbered migrations, the lint each one must pass, the one command
// path that applies them, and the version check the gateway makes instead of
// migrating.
//
// A Go-owned schema lives beside the existing application's tables in the
// same database, is owned by a NOLOGIN role holding no privilege on those
// tables, and is changed only by `schemactl`/`clusterctl migrate` (brief:
// "Disable automatic database migrations in all application startup paths").
package ownedschema

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Spec names one Go-owned schema and the files that build it.
type Spec struct {
	// Name is the schema. Nothing outside it is ever changed.
	Name string
	// OwnerRole owns the schema; migrations run as it (SET ROLE).
	OwnerRole string
	// WriterRole is the only role a migration may grant to.
	WriterRole string
	// Files holds NNNN_name.sql files at its root.
	Files fs.FS
	// LockKey serialises migration runs (pg_advisory_xact_lock).
	LockKey int64
}

// Migration is one numbered file.
type Migration struct {
	Version  int
	Name     string
	SQL      string
	Checksum string
}

var identifier = regexp.MustCompile(`^[a-z_][a-z0-9_]*$`)

func (s Spec) check() error {
	for _, name := range []string{s.Name, s.OwnerRole, s.WriterRole} {
		if !identifier.MatchString(name) {
			return fmt.Errorf("ownedschema: %q is not a plain lower-case identifier", name)
		}
	}
	if s.Files == nil || s.LockKey == 0 {
		return fmt.Errorf("ownedschema: %s needs its migration files and a lock key", s.Name)
	}
	return nil
}

// Load returns the shipped migrations in order, each linted, numbered from 1
// without gaps.
func (s Spec) Load() ([]Migration, error) {
	if err := s.check(); err != nil {
		return nil, err
	}
	names, err := fs.Glob(s.Files, "*.sql")
	if err != nil {
		return nil, fmt.Errorf("%s: listing migrations: %w", s.Name, err)
	}
	sort.Strings(names)
	migrations := make([]Migration, 0, len(names))
	for index, name := range names {
		raw, err := fs.ReadFile(s.Files, name)
		if err != nil {
			return nil, fmt.Errorf("%s: reading %s: %w", s.Name, name, err)
		}
		base := path.Base(name)
		number, _, found := strings.Cut(base, "_")
		version, err := strconv.Atoi(number)
		if !found || err != nil {
			return nil, fmt.Errorf("%s: %s must be named NNNN_name.sql", s.Name, base)
		}
		if version != index+1 {
			return nil, fmt.Errorf("%s: %s is version %d, want %d", s.Name, base, version, index+1)
		}
		if err := s.Lint(string(raw)); err != nil {
			return nil, fmt.Errorf("%s: %s: %w", s.Name, base, err)
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
func (s Spec) Required() int {
	migrations, err := s.Load()
	if err != nil || len(migrations) == 0 {
		return 0
	}
	return migrations[len(migrations)-1].Version
}
