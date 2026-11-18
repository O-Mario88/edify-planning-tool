// Package country is Edify Global's country registry as the gateway reads it
// (docs/migration/80-multi-country-phase-0.md): the countries the platform
// serves, which of them a reader may work in, and which country a school
// belongs to. The tables are internal/country/schema's; this package only
// reads them, apart from the one-off legacy seed (seed.go).
//
// Fail-closed throughout: a reader with no current membership of an Active
// country is given no country, and a school whose country cannot be
// established belongs to none.
package country

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
)

// Querier is what reading the registry needs.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Lifecycle states (country_registry.country.state). Only an Active country
// is worked in.
const (
	StateDraft         = "draft"
	StateValidated     = "validated"
	StateReadyForPilot = "ready_for_pilot"
	StateActive        = "active"
	StateSuspended     = "suspended"
	StateArchived      = "archived"
)

// Country is one registered country.
type Country struct {
	ID, Code, Name, State string
}

// WriteFor declares, for the rest of tx, which countries it writes rows for
// (registry ids) and whether it may change the countries and their names
// themselves. The registry's row-level security
// (schema/migrations/0002_row_security.sql) refuses any other write, so a
// transaction that declares nothing writes nothing.
func WriteFor(ctx context.Context, tx pgx.Tx, platform bool, countryIDs ...string) error {
	flag := ""
	if platform {
		flag = "on"
	}
	if _, err := tx.Exec(ctx, `SELECT set_config('edify.write_countries', $1, true), set_config('edify.platform_write', $2, true)`,
		strings.Join(countryIDs, ","), flag); err != nil {
		return fmt.Errorf("country: declaring the countries written: %w", err)
	}
	return nil
}

// current is "in force today" for an effective-dated row aliased r.
func current(r string) string {
	return fmt.Sprintf(`%[1]s.effective_from <= current_date AND (%[1]s.effective_until IS NULL OR %[1]s.effective_until > current_date)`, r)
}

// Memberships are the Active countries the account currently belongs to, its
// default first, then by code.
func Memberships(ctx context.Context, q Querier, userID string) ([]Country, error) {
	rows, err := q.Query(ctx, `SELECT c.id::text, c.code, c.name, c.state
FROM country_registry.country_membership m JOIN country_registry.country c ON c.id = m.country_id
WHERE m.user_id = $1 AND m.revoked_at IS NULL AND `+current("m")+` AND c.state = $2
ORDER BY m.is_default DESC, c.code`, userID, StateActive)
	if err != nil {
		return nil, fmt.Errorf("country: reading the account's countries: %w", err)
	}
	defer rows.Close()
	out := []Country{}
	for rows.Next() {
		var c Country
		if err := rows.Scan(&c.ID, &c.Code, &c.Name, &c.State); err != nil {
			return nil, fmt.Errorf("country: reading a country: %w", err)
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// Readable are the Active countries an account works in, by code: those it
// currently belongs to, or, for an account with no membership at all, the
// country its profile names (profileName, as staff_profile.country holds it).
func Readable(ctx context.Context, q Querier, userID, profileName string) ([]Country, error) {
	rows, err := q.Query(ctx, `SELECT c.id::text, c.code, c.name, c.state FROM country_registry.country c
WHERE c.state = $3 AND (EXISTS (
    SELECT 1 FROM country_registry.country_membership m
    WHERE m.country_id = c.id AND m.user_id = $1 AND m.revoked_at IS NULL AND `+current("m")+`)
  OR (NOT EXISTS (SELECT 1 FROM country_registry.country_membership m WHERE m.user_id = $1)
    AND EXISTS (SELECT 1 FROM country_registry.country_alias a WHERE a.country_id = c.id AND a.alias = $2)))
ORDER BY c.code`, userID, profileName, StateActive)
	if err != nil {
		return nil, fmt.Errorf("country: reading the account's countries: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Country, error) {
		var c Country
		return c, row.Scan(&c.ID, &c.Code, &c.Name, &c.State)
	})
}

// ReaderCountryIDs is the registry id of the country a country-wide reader
// is scoped to, named as the existing tables name it (staff_profile.country)
// and Active. An account with memberships keeps it only when one of them is
// that country; an account with none at all — one the existing application
// created after the registry was seeded — keeps its profile's country, as a
// school without an explicit country keeps its region's. None otherwise: an
// unknown name, a Draft country or a membership elsewhere gives the reader
// no country at all.
func ReaderCountryIDs(ctx context.Context, q Querier, userID, name string) ([]string, error) {
	rows, err := q.Query(ctx, `SELECT c.id::text
FROM country_registry.country_alias a JOIN country_registry.country c ON c.id = a.country_id
WHERE a.alias = $1 AND c.state = $3 AND (EXISTS (
    SELECT 1 FROM country_registry.country_membership m
    WHERE m.country_id = c.id AND m.user_id = $2 AND m.revoked_at IS NULL AND `+current("m")+`)
  OR NOT EXISTS (SELECT 1 FROM country_registry.country_membership m WHERE m.user_id = $2))`, name, userID, StateActive)
	if err != nil {
		return nil, fmt.Errorf("country: resolving the reader's country: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("country: resolving the reader's country: %w", err)
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// SchoolIn is the SQL that a school (aliased by school, the existing school
// table) belongs to one of the countries whose registry ids the placeholder
// ids holds (a text[] argument).
//
// The school's explicit country (country_registry.school_country) decides
// when it has one. A school without one — created by the existing
// application after the registry was seeded — is placed by its region's
// country, or, with no region, by its holder's, each read through the
// registry's names. A school with neither belongs to no country: the
// existing rule placed it in every country, which with a second country
// would have shown it to both (docs/migration/80-multi-country-phase-0.md,
// §1.2).
func SchoolIn(school, ids string) string {
	return fmt.Sprintf(`(EXISTS (SELECT 1 FROM country_registry.school_country sin_sc
  WHERE sin_sc.school_id = %[1]s.id AND sin_sc.country_id::text = ANY(%[2]s) AND `+current("sin_sc")+`)
 OR (NOT EXISTS (SELECT 1 FROM country_registry.school_country sin_sc WHERE sin_sc.school_id = %[1]s.id AND `+current("sin_sc")+`)
  AND (EXISTS (SELECT 1 FROM region sin_r JOIN country_registry.country_alias sin_a ON sin_a.alias = sin_r.country
        WHERE sin_r.id = %[1]s.region_id AND sin_a.country_id::text = ANY(%[2]s))
    OR (%[1]s.region_id IS NULL AND EXISTS (SELECT 1 FROM staff_profile sin_sp JOIN country_registry.country_alias sin_a ON sin_a.alias = sin_sp.country
        WHERE sin_sp.id = %[1]s.account_owner_id AND sin_sp.deleted_at IS NULL AND sin_a.country_id::text = ANY(%[2]s))))))`, school, ids)
}
