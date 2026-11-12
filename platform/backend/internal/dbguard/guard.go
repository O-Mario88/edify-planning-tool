// Package dbguard keeps the gateway away from the production database.
//
// It works in two steps. CheckDSN runs before any connection is opened and
// refuses a connection string whose host is not explicitly allowed for the
// environment, or that looks like the production endpoint. VerifyIdentity
// runs on the first connection and refuses a database role that could write
// to the tables the existing application owns.
//
// Neither step is a comment or a convention: main() cannot build a connection
// pool without passing both.
package dbguard

import (
	"context"
	"errors"
	"fmt"
	"net"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
)

// builtinProductionMarkers identify the production database and site. A host
// or database name containing one is refused in every environment this build
// can run in. Deployments add their exact production hostname through
// EDIFY_DB_PRODUCTION_MARKERS.
var builtinProductionMarkers = []string{
	"edify-production-db",
	"edifyplanning.app",
}

// protectedTables are tables the existing application owns. The gateway role
// must not be able to change any column of them, or remove their rows.
var protectedTables = []string{"school", "staff_school_assignment"}

// protectedAccountColumns are the columns of "user" the gateway may never
// change on an existing account. Go owns signing in and account
// administration (owner brief, 2026-11-11), so it writes the lockout,
// password, status, name, email and role columns (deploy/db/identity_roles.sql)
// — but never who is a superuser or staff, never second-factor enrolment, and
// never a DELETE: removal is the existing soft delete.
var protectedAccountColumns = []string{
	"id", "is_superuser", "is_staff", "mfa_enabled", "mfa_secret", "mfa_channel",
}

// undeletableTables are records Go now writes (the first save, scheduling a
// school visit: deploy/db/activities_roles.sql) or appends to, and must never
// remove: removal is the existing soft delete, and the audit chain and its
// events are append-only.
var undeletableTables = []string{
	"activity", "daily_visit_batch", "daily_visit_costs_to_follow", "audit_log", "domain_event_log",
}

// protectedColumns ("table.column") are what the first save may insert but
// never change afterwards: an activity's lifecycle, price, verification and
// payment, a day's priced figures, and any audit row. Setting them is the
// pricing's (Django's until M12) and the later saves' work.
var protectedColumns = []string{
	"activity.status", "activity.est_cost_cents", "activity.cost_missing", "activity.payment_status",
	"activity.ia_verification_status", "activity.evidence_status", "activity.responsible_staff_id",
	"activity.school_id", "activity.daily_visit_batch_id",
	"daily_visit_batch.daily_pool_amount", "daily_visit_batch.per_school_amount",
	"daily_visit_batch.school_count", "daily_visit_batch.rate_snapshot",
	"audit_log.hash", "audit_log.prev_hash", "audit_log.seq", "audit_log.payload",
}

// ErrRefused wraps every refusal, so callers can tell a guard decision from
// an ordinary connection failure.
var ErrRefused = errors.New("dbguard: connection refused by the production-protection guard")

// Policy is what the guard needs to know about the running process.
type Policy struct {
	Env               config.Environment
	AllowedHosts      []string
	ProductionMarkers []string
}

// PolicyFrom builds the guard policy for a loaded configuration.
func PolicyFrom(cfg config.Config) Policy {
	return Policy{
		Env:               cfg.Env,
		AllowedHosts:      cfg.DBAllowedHosts,
		ProductionMarkers: cfg.DBProductionMarkers,
	}
}

// Target describes the database a DSN points at, without credentials.
type Target struct {
	Hosts    []string
	Database string
	User     string
}

// CheckDSN parses dsn and returns its target, or ErrRefused when the policy
// forbids connecting to it. It opens no connection.
func CheckDSN(policy Policy, dsn string) (Target, error) {
	if policy.Env == config.Production {
		return Target{}, refuse("this build may not run against production")
	}
	parsed, err := pgconn.ParseConfig(dsn)
	if err != nil {
		// The parse error can echo the DSN, credentials included.
		return Target{}, refuse("the database URL could not be parsed")
	}

	target := Target{Database: parsed.Database, User: parsed.User, Hosts: hostsOf(parsed)}
	markers := append(append([]string{}, builtinProductionMarkers...), policy.ProductionMarkers...)

	for _, candidate := range append(append([]string{}, target.Hosts...), target.Database) {
		if marker, found := matchMarker(candidate, markers); found {
			return Target{}, refuse(fmt.Sprintf("%q matches the production marker %q", candidate, marker))
		}
	}
	for _, host := range target.Hosts {
		if !hostAllowed(policy, host) {
			return Target{}, refuse(fmt.Sprintf(
				"host %q is not in EDIFY_DB_ALLOWED_HOSTS for the %s environment", host, policy.Env,
			))
		}
	}
	if policy.Env == config.Staging && parsed.TLSConfig == nil {
		return Target{}, refuse("staging connections must use TLS (sslmode=require or stricter)")
	}
	return target, nil
}

// Querier is the single query VerifyIdentity needs; *pgx.Conn and
// *pgxpool.Pool both satisfy it.
type Querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Identity is what the connected database says about itself.
type Identity struct {
	Database  string
	Role      string
	Superuser bool
	// WritableTables lists the protected tables the role holds a write
	// privilege on, the append-only tables whose rows it could remove ("audit_log
	// (rows removable)") and the protected columns it could change ("activity.status").
	WritableTables []string
}

// VerifyIdentity asks the connected database who the gateway is and what it
// may change. A superuser, or a role that can write to a protected table, is
// refused in staging; in development and test it is reported in Identity so
// the caller can log it.
func VerifyIdentity(ctx context.Context, policy Policy, db Querier) (Identity, error) {
	var identity Identity
	const query = `
SELECT current_database(),
       current_user,
       COALESCE((SELECT rolsuper FROM pg_roles WHERE rolname = current_user), false),
       ARRAY(
         SELECT t FROM unnest($1::text[]) AS t
         WHERE to_regclass(quote_ident(t)) IS NOT NULL
           AND (has_any_column_privilege(current_user, quote_ident(t), 'INSERT')
             OR has_any_column_privilege(current_user, quote_ident(t), 'UPDATE')
             OR has_table_privilege(current_user, quote_ident(t), 'DELETE'))
         UNION ALL
         SELECT 'user' WHERE to_regclass('"user"') IS NOT NULL
           AND (has_table_privilege(current_user, '"user"', 'INSERT')
             OR has_table_privilege(current_user, '"user"', 'DELETE'))
         UNION ALL
         SELECT 'user.' || c FROM unnest($2::text[]) AS c
         WHERE to_regclass('"user"') IS NOT NULL
           AND has_column_privilege(current_user, '"user"', c, 'UPDATE')
         UNION ALL
         SELECT t || ' (rows removable)' FROM unnest($3::text[]) AS t
         WHERE to_regclass(quote_ident(t)) IS NOT NULL
           AND has_table_privilege(current_user, quote_ident(t), 'DELETE')
         UNION ALL
         SELECT tc FROM unnest($4::text[]) AS tc
         WHERE to_regclass(quote_ident(split_part(tc, '.', 1))) IS NOT NULL
           -- CASE, not AND: AND does not promise to skip the privilege
           -- check, which fails on a column the schema lacks.
           AND CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                                 WHERE table_schema = 'public'
                                   AND table_name = split_part(tc, '.', 1)
                                   AND column_name = split_part(tc, '.', 2))
                    THEN has_column_privilege(current_user, quote_ident(split_part(tc, '.', 1)),
                                              split_part(tc, '.', 2), 'UPDATE')
                    ELSE false END
       )`
	err := db.QueryRow(ctx, query, protectedTables, protectedAccountColumns,
		undeletableTables, protectedColumns).Scan(
		&identity.Database, &identity.Role, &identity.Superuser, &identity.WritableTables,
	)
	if err != nil {
		return Identity{}, fmt.Errorf("dbguard: reading the database identity: %w", err)
	}

	markers := append(append([]string{}, builtinProductionMarkers...), policy.ProductionMarkers...)
	if marker, found := matchMarker(identity.Database, markers); found {
		return identity, refuse(fmt.Sprintf("connected database %q matches the production marker %q", identity.Database, marker))
	}
	if policy.Env != config.Staging {
		return identity, nil
	}
	if identity.Superuser {
		return identity, refuse(fmt.Sprintf("role %q is a superuser; staging needs the read-only gateway role", identity.Role))
	}
	if len(identity.WritableTables) > 0 {
		return identity, refuse(fmt.Sprintf(
			"role %q can write to %s; staging needs the read-only gateway role",
			identity.Role, strings.Join(identity.WritableTables, ", "),
		))
	}
	return identity, nil
}

func refuse(reason string) error {
	return fmt.Errorf("%w: %s", ErrRefused, reason)
}

func hostsOf(parsed *pgconn.Config) []string {
	hosts := []string{strings.ToLower(parsed.Host)}
	for _, fallback := range parsed.Fallbacks {
		host := strings.ToLower(fallback.Host)
		if !contains(hosts, host) {
			hosts = append(hosts, host)
		}
	}
	return hosts
}

func matchMarker(candidate string, markers []string) (string, bool) {
	lowered := strings.ToLower(candidate)
	for _, marker := range markers {
		marker = strings.ToLower(strings.TrimSpace(marker))
		if marker != "" && strings.Contains(lowered, marker) {
			return marker, true
		}
	}
	return "", false
}

func hostAllowed(policy Policy, host string) bool {
	if contains(policy.AllowedHosts, host) {
		return true
	}
	// Staging never falls back to "anything local": its host is named.
	if policy.Env == config.Staging {
		return false
	}
	return isLocal(host)
}

// isLocal reports whether host is this machine: a unix socket directory, the
// name localhost, or a loopback address.
func isLocal(host string) bool {
	if host == "" || strings.HasPrefix(host, "/") || host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func contains(items []string, wanted string) bool {
	for _, item := range items {
		if item == wanted {
			return true
		}
	}
	return false
}
