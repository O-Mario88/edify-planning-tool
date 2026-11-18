package schooldirectory

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// Querier is the read the directory needs; *pgxpool.Pool satisfies it.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

const (
	roleAdmin           = "Admin"
	roleCCEO            = "CCEO"
	roleProgramLead     = "Program Lead"
	roleCountryDirector = "CountryDirector"
	roleImpact          = "ImpactAssessment"
	roleCoordinator     = "ProjectCoordinator"
)

// Scope is the part of the existing UserScope (apps.core.scoping) the
// directory reads, for a person working in their own role.
type Scope struct {
	Role, UserID, StaffID string
	CountryScope          bool
	// Country bounds a country-scoped role; empty means unbounded (Admin, or
	// a country role with no country on its profile), NoCountry that the
	// account does not belong to its profile's country.
	Country string
	// CountryID is that country's registry id, empty when Country is empty
	// or NoCountry; CountryFromRegistry that the country's roles (and so its
	// rosters) come from the registry rather than the existing profile
	// (docs/migration/80, §12 and §13).
	CountryID           string
	CountryFromRegistry bool
	RegionScope         bool
	RegionIDs           []string
	SummaryOnly         bool
	// OwnSchoolIDs is the direct portfolio: own schools and those of anyone
	// whose temporary coverage this person holds (or a coordinator's project
	// schools).
	OwnSchoolIDs []string
	// SchoolIDs is own and team, which decides whether projects are offered.
	SchoolIDs     []string
	OwnClusterIDs []string
	// OwnDistrictIDs are the direct portfolio's districts, and
	// SupervisedStaffIDs a lead's live supervisees (supervised_staff_ids):
	// what deciding who may run a piece of work reads.
	OwnDistrictIDs     []string
	SupervisedStaffIDs []string
}

// CountryIDs is the scope's country as the registry clauses take it (a
// text[] argument): its registry id, or one empty id, which matches no
// country, when the reader is bounded to NoCountry.
func (s Scope) CountryIDs() []string { return []string{s.CountryID} }

// NoCountry is the country of a reader whose profile names a country the
// account does not belong to (internal/country): no record carries it. It
// is passed to SQL as text, so it must stay valid UTF-8 without NUL bytes.
const NoCountry = "∅ no country membership"

func uniq(items []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, item := range items {
		if item != "" && !seen[item] {
			seen[item] = true
			out = append(out, item)
		}
	}
	return out
}

func strings1(ctx context.Context, q Querier, sql string, args ...any) ([]string, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (string, error) {
		var value *string
		err := row.Scan(&value)
		if value == nil {
			return "", err
		}
		return *value, err
	})
}

// resolveScope is _resolve_user_scope_uncached for the directory. now is the
// moment temporary coverage is read at.
func resolveScope(ctx context.Context, q Querier, p auth.Principal, now time.Time) (Scope, error) {
	s := Scope{Role: p.ActiveRole, UserID: p.UserID, StaffID: p.StaffProfileID}
	s.CountryScope = in(rules.CountryRoles, s.Role)
	s.SummaryOnly = in(rules.SummaryOnlyRoles, s.Role)
	s.RegionScope = in(rules.RegionRoles, s.Role)

	// An Impact Assessment assistant, overseen by an IA officer, works a
	// portfolio rather than the country (_overseen_by_impact_assessment).
	if s.Role == roleImpact && s.StaffID != "" {
		var overseen bool
		if err := q.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM staff_supervisor_assignment a
  JOIN staff_profile sup ON sup.id = a.supervisor_id AND sup.deleted_at IS NULL
  JOIN "user" su ON su.id = sup.user_id AND su.deleted_at IS NULL
  WHERE a.supervisee_id = $1 AND (su.active_role = $2 OR $2 = ANY(su.roles)))`, s.StaffID, roleImpact).Scan(&overseen); err != nil {
			return s, fmt.Errorf("schooldirectory: reading IA oversight: %w", err)
		}
		if overseen {
			s.CountryScope = false
		}
	}

	// Edify Global (docs/migration/80, §12): in a country whose roles come
	// from the registry, the role's scope is the one assigned there, not the
	// existing profile's.
	held, inRegistry := p.HeldInCountry()

	var err error
	switch {
	case (s.SummaryOnly || s.RegionScope) && inRegistry:
		s.RegionIDs = uniq(held.RegionIDs)
	case (s.SummaryOnly || s.RegionScope) && s.StaffID != "":
		if s.RegionIDs, err = assignedRegions(ctx, q, s.StaffID); err != nil {
			return s, err
		}
	case s.CountryScope:
	case (s.Role == roleCCEO || s.Role == roleProgramLead || s.Role == roleImpact) && s.StaffID != "":
		if err = s.portfolio(ctx, q, now); err != nil {
			return s, err
		}
	case s.Role == roleCoordinator && s.StaffID != "":
		if s.OwnSchoolIDs, err = strings1(ctx, q, `
SELECT psa.school_id FROM project_school_assignment psa
WHERE psa.project_id IN (
  SELECT p.id FROM project p WHERE p.deleted_at IS NULL AND (p.manager_staff_id = $1 OR EXISTS (
    SELECT 1 FROM project_staff_assignment a WHERE a.project_id = p.id AND a.staff_id = $1 AND a.is_active)))`, s.StaffID); err != nil {
			return s, fmt.Errorf("schooldirectory: reading project schools: %w", err)
		}
		s.SchoolIDs = uniq(s.OwnSchoolIDs)
		if s.OwnClusterIDs, s.OwnDistrictIDs, err = ownGeography(ctx, q, s.SchoolIDs); err != nil {
			return s, err
		}
	}

	if inRegistry {
		// The portfolio the existing tables give holds only the country's
		// own schools there.
		if err = s.withinCountry(ctx, q, p.Country.ID); err != nil {
			return s, err
		}
	}
	if s.RegionScope {
		assigned := s.RegionIDs
		if registry.IsRegional(s.Role) {
			// A regional role reaches every country's regions
			// (docs/migration/80, §15), not only those of the countries its
			// assigned regions are in.
			assigned = nil
		}
		if s.RegionIDs, err = regionalReach(ctx, q, assigned); err != nil {
			return s, err
		}
	}
	if registry.IsRegional(s.Role) {
		// A regional role is bounded by no country (docs/migration/80, §15):
		// a country-wide one (the Business Transformation Officer) reads every
		// country, as the Admin does.
		return s, nil
	}
	if s.CountryScope && s.Role != roleAdmin && inRegistry {
		s.Country, s.CountryID, s.CountryFromRegistry = p.Country.Name, p.Country.ID, true
	} else if s.CountryScope && s.Role != roleAdmin && s.StaffID != "" {
		var country *string
		err := q.QueryRow(ctx, `SELECT country FROM staff_profile WHERE id = $1`, s.StaffID).Scan(&country)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return s, fmt.Errorf("schooldirectory: reading the country: %w", err)
		}
		if country != nil {
			s.Country = strings.TrimSpace(*country)
		}
		if s.Country != "" {
			// Edify Global: the profile's country counts only while the
			// account belongs to it (internal/country). Otherwise the reader
			// is bounded to a country no record carries, so every reader of
			// s.Country — the directory's and each module's own — finds
			// nothing, rather than the empty "unbounded" it would mean.
			ids, err := registry.ReaderCountryIDs(ctx, q, s.UserID, s.Country)
			if err != nil {
				return s, err
			}
			if len(ids) == 0 {
				s.Country = NoCountry
			} else {
				s.CountryID = ids[0]
			}
		}
	}
	return s, nil
}

// withinCountry keeps, of the portfolio, the schools of the country whose
// registry id is countryID (country.SchoolIn), and reads its own clusters
// and districts again from what is left.
func (s *Scope) withinCountry(ctx context.Context, q Querier, countryID string) error {
	if len(s.SchoolIDs) == 0 && len(s.OwnSchoolIDs) == 0 {
		return nil
	}
	inside, err := strings1(ctx, q, `SELECT s.id FROM school s WHERE s.id = ANY($1) AND `+registry.SchoolIn("s", "$2"),
		uniq(append(append([]string{}, s.SchoolIDs...), s.OwnSchoolIDs...)), []string{countryID})
	if err != nil {
		return fmt.Errorf("schooldirectory: keeping the country's schools: %w", err)
	}
	keep := func(ids []string) []string {
		out := []string{}
		for _, id := range ids {
			if in(inside, id) {
				out = append(out, id)
			}
		}
		return out
	}
	s.OwnSchoolIDs, s.SchoolIDs = keep(s.OwnSchoolIDs), keep(s.SchoolIDs)
	s.OwnClusterIDs, s.OwnDistrictIDs, err = ownGeography(ctx, q, s.OwnSchoolIDs)
	return err
}

// portfolio is the CCEO, Program Lead and IA-assistant branch: own schools,
// with active temporary coverage, and a lead's supervised team.
func (s *Scope) portfolio(ctx context.Context, q Querier, now time.Time) error {
	covered, err := strings1(ctx, q, `
SELECT original_staff_id FROM temporary_coverage_assignment
WHERE covering_staff_id = $1 AND start_datetime <= $2 AND end_datetime >= $2 AND status = 'active'`, s.StaffID, now)
	if err != nil {
		return fmt.Errorf("schooldirectory: reading coverage: %w", err)
	}
	holders := append([]string{s.StaffID}, covered...)
	own, err := strings1(ctx, q, `SELECT school_id FROM staff_school_assignment WHERE staff_id = ANY($1)`, holders)
	if err != nil {
		return fmt.Errorf("schooldirectory: reading the portfolio: %w", err)
	}
	s.OwnSchoolIDs = uniq(own)

	leadsCover := false
	if len(covered) > 0 {
		if err := q.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.id = ANY($1) AND sp.deleted_at IS NULL AND (u.active_role = $2 OR $2 = ANY(u.roles)))`,
			covered, roleProgramLead).Scan(&leadsCover); err != nil {
			return fmt.Errorf("schooldirectory: reading covered leads: %w", err)
		}
	}
	team := []string{}
	if s.Role == roleProgramLead || leadsCover {
		supervisees, err := strings1(ctx, q, `
SELECT a.supervisee_id FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisee_id AND sp.deleted_at IS NULL
WHERE a.supervisor_id = ANY($1)`, holders)
		if err != nil {
			return fmt.Errorf("schooldirectory: reading the team: %w", err)
		}
		supervisees = uniq(supervisees)
		s.SupervisedStaffIDs = supervisees
		if len(supervisees) > 0 {
			schools, err := strings1(ctx, q, `SELECT school_id FROM staff_school_assignment WHERE staff_id = ANY($1)`, supervisees)
			if err != nil {
				return fmt.Errorf("schooldirectory: reading team schools: %w", err)
			}
			for _, id := range uniq(schools) {
				if !in(s.OwnSchoolIDs, id) {
					team = append(team, id)
				}
			}
		}
	}
	s.SchoolIDs = uniq(append(append([]string{}, s.OwnSchoolIDs...), team...))
	var err2 error
	s.OwnClusterIDs, s.OwnDistrictIDs, err2 = ownGeography(ctx, q, s.OwnSchoolIDs)
	return err2
}

// ownGeography is _derive_from_schools' own_cluster_ids and
// own_district_ids: the clusters and districts of the direct portfolio's
// live schools.
func ownGeography(ctx context.Context, q Querier, own []string) (clusters, districts []string, err error) {
	if len(own) == 0 {
		return nil, nil, nil
	}
	rows, err := q.Query(ctx, `
SELECT COALESCE(cluster_id, ''), COALESCE(district_id, '') FROM school WHERE id = ANY($1) AND deleted_at IS NULL ORDER BY id`, own)
	if err != nil {
		return nil, nil, fmt.Errorf("schooldirectory: reading own clusters: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var cluster, district string
		if err := rows.Scan(&cluster, &district); err != nil {
			return nil, nil, err
		}
		clusters, districts = append(clusters, cluster), append(districts, district)
	}
	return uniq(clusters), uniq(districts), rows.Err()
}

// assignedRegions is a region role's geography: its region rows, or the
// regions of its district rows.
func assignedRegions(ctx context.Context, q Querier, staffID string) ([]string, error) {
	regions, err := strings1(ctx, q, `
SELECT region_id FROM staff_geography_assignment WHERE staff_id = $1 AND region_id IS NOT NULL`, staffID)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading regions: %w", err)
	}
	if regions = uniq(regions); len(regions) > 0 {
		return regions, nil
	}
	regions, err = strings1(ctx, q, `
SELECT d.region_id FROM district d WHERE d.id IN (
  SELECT district_id FROM staff_geography_assignment WHERE staff_id = $1 AND district_id IS NOT NULL)`, staffID)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading district regions: %w", err)
	}
	return uniq(regions), nil
}

// regionalReach is _regional_reach: every region of the countries the
// assigned regions are in, or of every country when none is assigned.
func regionalReach(ctx context.Context, q Querier, assigned []string) ([]string, error) {
	countries := []string{}
	var err error
	if len(assigned) > 0 {
		if countries, err = strings1(ctx, q, `SELECT country FROM region WHERE id = ANY($1) ORDER BY country`, assigned); err != nil {
			return nil, err
		}
		countries = uniq(countries)
	}
	if len(countries) == 0 {
		if countries, err = strings1(ctx, q, `SELECT country FROM region ORDER BY country`); err != nil {
			return nil, err
		}
		countries = uniq(countries)
	}
	ids, err := strings1(ctx, q, `SELECT id FROM region WHERE country = ANY($1) ORDER BY name`, countries)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading regional reach: %w", err)
	}
	return uniq(ids), nil
}
