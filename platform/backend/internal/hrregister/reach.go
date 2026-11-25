package hrregister

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// reachKind is how a reach bounds a query (apps.hr.reach).
type reachKind int

const (
	reachNone reachKind = iota
	reachAll
	reachCountries
	reachTeam
)

// reach is apps.hr.reach.PeopleReach: whose People records a viewer reads.
type reach struct {
	kind      reachKind
	countries []string
	// viewer is the Programme Lead's own People record (a team's reach).
	viewer string
	// regional is a regional role's reach of every registered country.
	regional bool
}

// programmeLeads are apps.hr.reach's Programme Lead role names.
var programmeLeads = []string{"Program Lead", "ProgramLead"}

// peopleReach is people_reach: Admin (or a superuser) reads the
// organisation; a regional role, the Regional HR Director among them, the
// People records of every registered country (owner, 2026-11-18: the
// regional roles "should have access to all the countries"; the existing
// rule read the countries the director's geography named); a Programme Lead their own team; anyone else the country on their
// own People record, else nothing. Someone working in an acting appointment
// never reaches here (the page service passes them on). The viewer's own
// People record is read as user.staff_profile reads it: deleted or not.
func peopleReach(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (reach, error) {
	var superuser bool
	var viewer, country *string
	err := db.QueryRow(ctx, `
SELECT u.is_superuser, sp.id, sp.country
FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.id = $1`, p.UserID).Scan(&superuser, &viewer, &country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return reach{}, fmt.Errorf("hrregister: reading the viewer: %w", err)
	}
	if p.ActiveRole == "Admin" || superuser {
		return reach{kind: reachAll}, nil
	}
	if registry.IsRegional(p.ActiveRole) {
		// Every country, not everything (docs/migration/80, §15): a People
		// record that names no registered country stays the Admin's.
		names, err := everyCountryName(ctx, db)
		if err != nil {
			return reach{}, err
		}
		return reach{kind: reachCountries, countries: names, regional: true}, nil
	}
	// Edify Global (docs/migration/80, §12): in a country whose roles come
	// from the registry, a role held there reaches that country's People
	// records (a Programme Lead still their own team), not the countries
	// the existing profile or geography names.
	if _, inRegistry := p.HeldInCountry(); inRegistry {
		if slices.Contains(programmeLeads, p.ActiveRole) && viewer != nil {
			return reach{kind: reachTeam, viewer: *viewer}, nil
		}
		return reach{kind: reachCountries, countries: []string{p.Country.Name}}, nil
	}
	own := ""
	if country != nil {
		own = strings.TrimSpace(*country)
	}
	if slices.Contains(programmeLeads, p.ActiveRole) && viewer != nil {
		return reach{kind: reachTeam, viewer: *viewer}, nil
	}
	if own != "" {
		return reach{kind: reachCountries, countries: []string{own}}, nil
	}
	return reach{kind: reachNone}, nil
}

// everyCountryName is every name the registry gives a country (Uganda,
// UG, …), as the existing People records hold them.
func everyCountryName(ctx context.Context, db schooldirectory.Querier) ([]string, error) {
	rows, err := db.Query(ctx, `SELECT alias FROM country_registry.country_alias ORDER BY alias`)
	if err != nil {
		return nil, fmt.Errorf("hrregister: reading the countries: %w", err)
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("hrregister: reading the countries: %w", err)
	}
	return names, nil
}

// profiles is scope_profiles over the live People records of live accounts
// (_profile_scope), as a WHERE clause on staff_profile `sp`, its argument
// appended to args.
func (r reach) profiles(args []any) (string, []any) {
	switch r.kind {
	case reachAll:
		return "TRUE", args
	case reachCountries:
		args = append(args, r.countries)
		return fmt.Sprintf("sp.country = ANY($%d)", len(args)), args
	case reachTeam:
		args = append(args, r.viewer)
		n := len(args)
		return fmt.Sprintf("(sp.id = $%d OR EXISTS (SELECT 1 FROM staff_supervisor_assignment l WHERE l.supervisee_id = sp.id AND l.supervisor_id = $%d))", n, n), args
	}
	return "FALSE", args
}

// byCountry is scope_by_country: rows that carry their own country, read
// whole by an organisation's reach, by the reach's countries otherwise, and
// not at all by a team's reach or none.
func (r reach) byCountry(col string, args []any) (string, []any) {
	switch r.kind {
	case reachAll:
		return "TRUE", args
	case reachCountries:
		args = append(args, r.countries)
		return fmt.Sprintf("%s = ANY($%d)", col, len(args)), args
	}
	return "FALSE", args
}
