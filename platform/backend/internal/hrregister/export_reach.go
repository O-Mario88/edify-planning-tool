package hrregister

import (
	"context"
	"slices"
	"strconv"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PeopleReachProfiles is people_reach read through scope_profiles, for the
// pages outside the HR registers that ask it: a WHERE clause on
// staff_profile `sp` (the reach alone, without the registers' live-record
// conditions), its arguments appended to args, and whether the reach is the
// whole organisation (reach.is_everything).
func PeopleReachProfiles(ctx context.Context, db schooldirectory.Querier, p auth.Principal, args []any) (string, []any, bool, error) {
	r, err := peopleReach(ctx, db, p)
	if err != nil {
		return "", nil, false, err
	}
	where, args := r.profiles(args)
	return where, args, r.kind == reachAll, nil
}

// PeopleReachUsers is people_reach read through scope_users: a WHERE clause
// on "user" `u` (everyone for the organisation's reach; otherwise the users
// whose People record is in the reach's countries, or is the lead's own or
// one they supervise), its arguments appended to args, and whether the reach
// is a Programme Lead's team.
func PeopleReachUsers(ctx context.Context, db schooldirectory.Querier, p auth.Principal, args []any) (string, []any, bool, error) {
	r, err := peopleReach(ctx, db, p)
	if err != nil {
		return "", nil, false, err
	}
	if r.kind == reachAll {
		return "TRUE", args, false, nil
	}
	where, args := r.profiles(args)
	return "EXISTS (SELECT 1 FROM staff_profile sp WHERE sp.user_id = u.id AND " + where + ")", args, r.kind == reachTeam, nil
}

// PeopleReachLabel is people_reach(p).label() and whether the reach is none:
// "All countries", "Your team", the one country, "N countries", or "No
// countries".
func PeopleReachLabel(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (string, bool, error) {
	r, err := peopleReach(ctx, db, p)
	if err != nil {
		return "", false, err
	}
	switch r.kind {
	case reachAll:
		return "All countries", false, nil
	case reachTeam:
		return "Your team", false, nil
	case reachCountries:
		if len(r.countries) == 1 {
			return r.countries[0], false, nil
		}
		return strconv.Itoa(len(r.countries)) + " countries", false, nil
	}
	return "No countries", true, nil
}

// PeopleReachAllowsCountry is people_reach(p).allows_country(country): the
// organisation's reach allows any; a reach of countries allows its own (an
// empty country none); a team's or none, no country.
func PeopleReachAllowsCountry(ctx context.Context, db schooldirectory.Querier, p auth.Principal, country string) (bool, error) {
	r, err := peopleReach(ctx, db, p)
	if err != nil {
		return false, err
	}
	switch r.kind {
	case reachAll:
		return true, nil
	case reachCountries:
		return country != "" && slices.Contains(r.countries, country), nil
	}
	return false, nil
}

// PeopleReachCountryOptions is people_reach(p).filter_options(): the
// countries a form may offer. The organisation's reach offers every country
// a region or a People record names; a regional role's (owner, 2026-11-18:
// every country) each active registered country by name, not its codes; a
// reach of countries its own; a team's or none, nothing.
func PeopleReachCountryOptions(ctx context.Context, db schooldirectory.Querier, p auth.Principal) ([]string, bool, error) {
	r, err := peopleReach(ctx, db, p)
	if err != nil {
		return nil, false, err
	}
	query := ""
	switch {
	case r.kind == reachAll:
		query = `SELECT DISTINCT country FROM (SELECT country FROM region UNION SELECT country FROM staff_profile
WHERE deleted_at IS NULL) c WHERE country IS NOT NULL AND country <> '' ORDER BY country`
	case r.regional:
		query = `SELECT name FROM country_registry.country WHERE state = 'active' ORDER BY name`
	case r.kind == reachCountries:
		return append([]string{}, r.countries...), false, nil
	default:
		return nil, false, nil
	}
	rows, err := db.Query(ctx, query)
	if err != nil {
		return nil, false, err
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	return names, r.kind == reachAll, err
}

// PeopleReachCountries is the reach's own countries (reach.countries) and
// whether it is the whole organisation (reach.is_everything).
func PeopleReachCountries(ctx context.Context, db schooldirectory.Querier, p auth.Principal) ([]string, bool, error) {
	r, err := peopleReach(ctx, db, p)
	if err != nil {
		return nil, false, err
	}
	return append([]string{}, r.countries...), r.kind == reachAll, nil
}
