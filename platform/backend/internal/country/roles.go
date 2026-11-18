package country

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// Where a country's roles come from (country_registry.country.roles_source,
// docs/migration/80-multi-country-phase-0.md §12).
const (
	// RolesFromProfile: the account's roles and scope are the existing
	// application's (its profile, region and school assignments), exactly
	// as today. Uganda's.
	RolesFromProfile = "existing_profile"
	// RolesFromRegistry: the account works in the country only in the roles
	// an Admin assigned it there (country_role_assignment).
	RolesFromRegistry = "registry"
)

// Scope types of a role assigned in a country.
const (
	ScopeCountry   = "country"
	ScopeRegions   = "regions"
	ScopePortfolio = "portfolio"
)

// Assigned is one role an account holds in a country.
type Assigned struct {
	Role, ScopeType string
	// RegionIDs are the existing region ids a regional role covers.
	RegionIDs []string
}

// Work is the country a request is made in and, where that country's roles
// come from the registry, the roles the account holds there.
type Work struct {
	Country
	RolesSource string
	// MembershipID is the membership that gives the account the country;
	// empty when it works there through its profile (no membership at all).
	MembershipID string
	// Roles are the roles in force there, oldest first; read only when the
	// country's roles come from the registry.
	Roles []Assigned
}

// FromRegistry says whether the country's roles are the registry's.
func (w *Work) FromRegistry() bool { return w != nil && w.RolesSource == RolesFromRegistry }

// workingSQL is the Active country a request is made in: the account's
// default membership in force first, then the others by code; for an account
// with no membership at all, the Active country its profile names
// ($2, staff_profile.country as the existing table holds it).
var workingSQL = `SELECT id, code, name, state, roles_source, membership_id FROM (
  SELECT c.id::text, c.code, c.name, c.state, c.roles_source, m.id::text AS membership_id, 0 AS rank, NOT m.is_default AS later
  FROM country_registry.country_membership m JOIN country_registry.country c ON c.id = m.country_id
  WHERE m.user_id = $1 AND m.revoked_at IS NULL AND ` + current("m") + ` AND c.state = 'active'
  UNION ALL
  SELECT c.id::text, c.code, c.name, c.state, c.roles_source, '', 1, false
  FROM country_registry.country_alias a JOIN country_registry.country c ON c.id = a.country_id
  WHERE a.alias = $2 AND c.state = 'active'
    AND NOT EXISTS (SELECT 1 FROM country_registry.country_membership x WHERE x.user_id = $1)
) w ORDER BY rank, later, code LIMIT 1`

// Working is the country a request by userID is made in, or nil when the
// account works in no Active country (its memberships are all revoked,
// ended or of countries not yet Active, or it has none and its profile names
// no Active country). Where the country's roles come from the registry, the
// roles the account holds there are read with it; an account with none
// there holds no role in it.
func Working(ctx context.Context, q Querier, userID, profileCountry string) (*Work, error) {
	w := &Work{}
	err := q.QueryRow(ctx, workingSQL, userID, profileCountry).Scan(&w.ID, &w.Code, &w.Name, &w.State, &w.RolesSource, &w.MembershipID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("country: reading the country the request is made in: %w", err)
	}
	if !w.FromRegistry() || w.MembershipID == "" {
		return w, nil
	}
	rows, err := q.Query(ctx, `SELECT role_name, scope_type, region_ids FROM country_registry.country_role_assignment
WHERE membership_id = $1::uuid AND revoked_at IS NULL ORDER BY granted_at, role_name`, w.MembershipID)
	if err != nil {
		return nil, fmt.Errorf("country: reading the account's roles in %s: %w", w.Code, err)
	}
	w.Roles, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (Assigned, error) {
		var a Assigned
		return a, row.Scan(&a.Role, &a.ScopeType, &a.RegionIDs)
	})
	if err != nil {
		return nil, fmt.Errorf("country: reading the account's roles in %s: %w", w.Code, err)
	}
	return w, nil
}
