package hrregister

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
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
}

// hrDirector and programmeLeads are apps.hr.reach's role names.
const hrDirector = "HumanResources"

var programmeLeads = []string{"Program Lead", "ProgramLead"}

// peopleReach is people_reach: Admin (or a superuser) reads the
// organisation; the Regional HR Director the countries their assigned
// geography names, else the country on their own People record, else
// nothing; a Programme Lead their own team; anyone else the country on their
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
	own := ""
	if country != nil {
		own = strings.TrimSpace(*country)
	}
	switch {
	case p.ActiveRole == hrDirector:
		countries, err := directorCountries(ctx, db, viewer)
		if err != nil {
			return reach{}, err
		}
		if len(countries) > 0 {
			return reach{kind: reachCountries, countries: countries}, nil
		}
	case slices.Contains(programmeLeads, p.ActiveRole) && viewer != nil:
		return reach{kind: reachTeam, viewer: *viewer}, nil
	}
	if own != "" {
		return reach{kind: reachCountries, countries: []string{own}}, nil
	}
	return reach{kind: reachNone}, nil
}

// directorCountries is _director_countries: the countries of the regions the
// director's geography assignments name (directly, or through a district).
func directorCountries(ctx context.Context, db schooldirectory.Querier, viewer *string) ([]string, error) {
	if viewer == nil {
		return nil, nil
	}
	rows, err := db.Query(ctx, `
SELECT DISTINCT r.country FROM region r
WHERE r.country <> '' AND r.id IN (
  SELECT region_id FROM staff_geography_assignment WHERE staff_id = $1 AND region_id IS NOT NULL
  UNION
  SELECT d.region_id FROM staff_geography_assignment a JOIN district d ON d.id = a.district_id WHERE a.staff_id = $1)
ORDER BY r.country`, *viewer)
	if err != nil {
		return nil, fmt.Errorf("hrregister: reading the director's countries: %w", err)
	}
	countries, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("hrregister: reading the director's countries: %w", err)
	}
	return countries, nil
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
