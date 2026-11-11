package dbguard

import (
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
)

func TestCheckDSN(t *testing.T) {
	tests := []struct {
		name    string
		policy  Policy
		dsn     string
		refused string // substring of the refusal; empty means allowed
	}{
		{
			name:   "development on localhost",
			policy: Policy{Env: config.Development},
			dsn:    "postgresql://edify_gateway@localhost:5432/edify_gorn_dev",
		},
		{
			name:   "development on loopback address",
			policy: Policy{Env: config.Development},
			dsn:    "postgresql://edify_gateway@127.0.0.1:5432/edify_gorn_dev",
		},
		{
			name:   "test over a unix socket",
			policy: Policy{Env: config.Test},
			dsn:    "host=/tmp dbname=edify_gorn_test user=edify_gateway",
		},
		{
			name:    "production environment is never allowed",
			policy:  Policy{Env: config.Production},
			dsn:     "postgresql://localhost/edify",
			refused: "may not run against production",
		},
		{
			name:    "the production cluster name is refused",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://u:p@edify-production-db-do-user-1.b.db.ondigitalocean.com:25060/defaultdb?sslmode=require",
			refused: "production marker",
		},
		{
			name:    "the production marker is refused even when allow-listed",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"edify-production-db.example.com"}},
			dsn:     "postgresql://u:p@edify-production-db.example.com/db?sslmode=require",
			refused: "production marker",
		},
		{
			name:    "a configured production hostname is refused",
			policy:  Policy{Env: config.Development, ProductionMarkers: []string{"db-live-01"}},
			dsn:     "postgresql://u:p@DB-LIVE-01.internal/db",
			refused: "production marker",
		},
		{
			name:    "a production marker in the database name is refused",
			policy:  Policy{Env: config.Development, ProductionMarkers: []string{"edify_live"}},
			dsn:     "postgresql://localhost/edify_live",
			refused: "production marker",
		},
		{
			name:    "development may not reach a remote host",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://u:p@10.20.0.5:5432/edify",
			refused: "not in EDIFY_DB_ALLOWED_HOSTS",
		},
		{
			name:    "a remote fallback host is refused",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://u:p@localhost:5432,remote.example.com:5432/edify",
			refused: "not in EDIFY_DB_ALLOWED_HOSTS",
		},
		{
			name:    "staging never falls back to localhost",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:     "postgresql://u:p@localhost/edify?sslmode=require",
			refused: "not in EDIFY_DB_ALLOWED_HOSTS",
		},
		{
			name:    "staging requires TLS",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:     "postgresql://u:p@staging-db.internal/edify?sslmode=disable",
			refused: "must use TLS",
		},
		{
			name:   "staging on its named host with TLS",
			policy: Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:    "postgresql://u:p@staging-db.internal/edify?sslmode=require",
		},
		{
			name:    "an unparseable URL is refused without echoing it",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://user:s3cret@localhost:notaport/db",
			refused: "could not be parsed",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := CheckDSN(test.policy, test.dsn)
			if test.refused == "" {
				if err != nil {
					t.Fatalf("unexpected refusal: %v", err)
				}
				return
			}
			if !errors.Is(err, ErrRefused) {
				t.Fatalf("want ErrRefused, got %v", err)
			}
			if !strings.Contains(err.Error(), test.refused) {
				t.Fatalf("want refusal containing %q, got %v", test.refused, err)
			}
			if strings.Contains(err.Error(), "s3cret") {
				t.Fatalf("the refusal leaks the password: %v", err)
			}
		})
	}
}

// The gateway never writes to or changes the existing application's schema.
// This test fails the build if a write, a DDL statement or an ORM
// auto-migration call appears in its sources, with sanctioned exceptions for
// the Go-owned schemas only:
//
//   - inside internal/clusterlead a write may target only cluster_leadership
//     tables, and inside internal/loans only school_loans tables;
//   - DDL appears only in internal/ownedschema, the shared migration
//     mechanics, and only on a schema's own migration ledger
//     (%s.schema_migration, %s being the schema's checked name);
//   - nothing anywhere may remove a table, its rows or its data.
func TestGatewaySourcesContainNoSchemaChanges(t *testing.T) {
	forbidden := regexp.MustCompile(
		`(?i)\b(CREATE|ALTER|DROP|TRUNCATE)\s+(TABLE|INDEX|SCHEMA|DATABASE|SEQUENCE|TRIGGER)\b|AutoMigrate|\bINSERT\s+INTO\b|\bUPDATE\s+\S+\s+SET\b|\bDELETE\s+FROM\b`,
	)
	root := filepath.Join("..", "..")
	sep := string(filepath.Separator)
	// Where a write may appear, and the schema it must name.
	writers := map[string]string{
		filepath.Join(root, "internal", "clusterlead") + sep: "cluster_leadership.",
		filepath.Join(root, "internal", "loans") + sep:       "school_loans.",
	}
	// Signing in and account administration, which Go owns (owner brief,
	// 2026-11-11), write the existing account tables, and the audit chain
	// appends to the existing log: those packages and tables only, never a
	// removal or DDL. The
	// database role enforces the same columns (deploy/db/identity_roles.sql).
	existingWriters := map[string][]string{
		filepath.Join(root, "internal", "signin") + sep: {
			`"user"`, "refresh_token", "mfa_challenge", "user_invitation", "staff_profile", "login_event",
		},
		filepath.Join(root, "internal", "audit") + sep: {"audit_log", "domain_event_log"},
		filepath.Join(root, "internal", "accounts") + sep: {
			`"user"`, "refresh_token", "user_invitation", "staff_profile", "staff_geography_assignment",
		},
		filepath.Join(root, "internal", "teams") + sep: {
			"staff_supervisor_assignment", "partner_member", "partner_school_member", "activity",
		},
		// Acting appointments, and the account's acting hint and role in use.
		filepath.Join(root, "internal", "acting") + sep: {"acting_assignment", `"user"`},
	}
	mechanics := filepath.Join(root, "internal", "ownedschema") + sep
	// The lint describes the DDL it allows as patterns; it runs none.
	lint := filepath.Join(root, "internal", "ownedschema", "lint.go")
	removes := func(statement string) bool {
		upper := strings.ToUpper(statement)
		return strings.Contains(upper, "DROP") || strings.Contains(upper, "TRUNCATE") ||
			strings.Contains(upper, "DELETE") || strings.Contains(upper, "AUTOMIGRATE")
	}
	targetOf := func(source []byte, match []int) string {
		statement := string(source[match[0]:match[1]])
		if strings.HasPrefix(strings.ToUpper(statement), "UPDATE") {
			return strings.TrimSpace(statement[len("UPDATE"):])
		}
		after := strings.TrimSpace(string(source[match[1]:]))
		for _, filler := range []string{"IF NOT EXISTS", "IF EXISTS", "ONLY"} {
			if strings.HasPrefix(strings.ToUpper(after), filler) {
				after = strings.TrimSpace(after[len(filler):])
			}
		}
		return after
	}
	// The one removal allowed: team link rows the existing code itself
	// deletes when a reporting line or a school split changes, and a roster
	// entry removed (apps/accounts/supervisor_service.py, apps/partners). The
	// role grants DELETE on these three tables and no other.
	teamsDir := filepath.Join(root, "internal", "teams") + sep
	removableLinks := []string{"staff_supervisor_assignment", "partner_member", "partner_school_member"}
	allowed := func(path string, source []byte, match []int) bool {
		statement := string(source[match[0]:match[1]])
		if removes(statement) {
			if !strings.HasPrefix(path, teamsDir) || !strings.HasPrefix(strings.ToUpper(statement), "DELETE FROM") {
				return false
			}
			target := targetOf(source, match)
			for _, table := range removableLinks {
				if strings.HasPrefix(target, table+" ") {
					return true
				}
			}
			return false
		}
		target := targetOf(source, match)
		if strings.HasPrefix(path, mechanics) {
			return strings.HasPrefix(target, "%s.schema_migration")
		}
		isDDL := regexp.MustCompile(`(?i)^(CREATE|ALTER)`).MatchString(statement)
		for dir, schema := range writers {
			if strings.HasPrefix(path, dir) && !isDDL {
				return strings.HasPrefix(strings.ToLower(target), schema)
			}
		}
		for dir, tables := range existingWriters {
			if !strings.HasPrefix(path, dir) || isDDL {
				continue
			}
			for _, table := range tables {
				if strings.HasPrefix(target, table+" ") || strings.HasPrefix(target, table+"(") {
					return true
				}
			}
		}
		return false
	}
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			if entry.Name() == "gen" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		source, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		if path == lint {
			return nil
		}
		for _, match := range forbidden.FindAllIndex(source, -1) {
			if !allowed(path, source, match) {
				t.Errorf("%s contains a write or schema statement: %q", path, string(source[match[0]:match[1]]))
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
