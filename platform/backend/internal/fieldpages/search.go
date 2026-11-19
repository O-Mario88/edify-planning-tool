package fieldpages

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Search with a query (extended_views.search_view, pages/search/index.html):
// the reader's direct-portfolio schools, the staff the directory's roles may
// open (a country's own unless the role's directory spans countries), and
// the work list_activities reaches at a school or cluster of that name; ten
// of each, newest first.

const searchLimit = 10

var partnerRoles = []string{"PartnerAdmin", "PartnerFieldOfficer"}

// likeOf is icontains' pattern: the query anywhere, its wildcards literal.
func likeOf(q string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(q) + "%"
}

type found struct{ text, href, caption string }

// oneLine is text as the feed reads it.
func oneLine(s string) string { return strings.Join(strings.Fields(s), " ") }

func (s *Service) search(ctx context.Context, p auth.Principal, q string) (*screensv1.GetPageResponse, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, err
	}
	like := likeOf(q)
	schools, err := s.searchSchools(ctx, scope, like)
	if err != nil {
		return nil, err
	}
	var staff []found
	if rules.Roles[p.ActiveRole].SearchStaff {
		if staff, err = s.searchStaff(ctx, p, like); err != nil {
			return nil, err
		}
	}
	work, err := s.searchWork(ctx, p, scope, like)
	if err != nil {
		return nil, err
	}
	blocks := []*screensv1.PageBlock{panel(text("Showing results for " + q))}
	for _, section := range []struct {
		title string
		rows  []found
	}{{"Schools", schools}, {"Staff", staff}, {"Activities", work}} {
		if len(section.rows) == 0 {
			continue
		}
		ls := make([]*screensv1.PageLink, 0, len(section.rows))
		for _, r := range section.rows {
			ls = append(ls, &screensv1.PageLink{Text: r.text, Href: r.href, Caption: r.caption})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: section.title, Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}},
		}}})
	}
	if len(blocks) == 1 {
		blocks = append(blocks, panel(text(`No results found for "`+q+`"`)))
	}
	return page(header("Search", "Search", "Edify Operations · Search"), searchPath, blocks...), nil
}

func collect(rows pgx.Rows, what string) ([]found, error) {
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (found, error) {
		var f found
		return f, r.Scan(&f.text, &f.href, &f.caption)
	})
	if err != nil {
		return nil, fmt.Errorf("fieldpages: searching %s: %w", what, err)
	}
	return out, nil
}

// searchSchools is direct_portfolio_schools of that name, not deleted.
func (s *Service) searchSchools(ctx context.Context, scope schooldirectory.Scope, like string) ([]found, error) {
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	where := schooldirectory.DirectPortfolio(scope, arg)
	rows, err := s.db.Query(ctx, `SELECT s.name, '/schools/' || s.id, '' FROM school s
WHERE `+where+` AND UPPER(s.name::text) LIKE UPPER(`+arg(like)+`) AND s.deleted_at IS NULL
ORDER BY s.created_at DESC LIMIT `+arg(searchLimit), args...)
	if err != nil {
		return nil, fmt.Errorf("fieldpages: searching schools: %w", err)
	}
	return collect(rows, "schools")
}

// searchStaff is the people of that name, not deleted; held to the
// reader's country (documents.country_of: their profile's) unless their
// role's directory spans countries, and to none when they have no country.
func (s *Service) searchStaff(ctx context.Context, p auth.Principal, like string) ([]found, error) {
	var superuser bool
	var country string
	err := s.db.QueryRow(ctx, `SELECT u.is_superuser, COALESCE(sp.country, '')
FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id WHERE u.id = $1`, p.UserID).Scan(&superuser, &country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("fieldpages: reading the reader's country: %w", err)
	}
	args := []any{like}
	held := ""
	if !superuser && !slices.Contains(rules.EveryCountrySearchRoles, p.ActiveRole) {
		if country == "" {
			return nil, nil
		}
		args = append(args, country)
		held = " AND EXISTS (SELECT 1 FROM staff_profile sp WHERE sp.user_id = u.id AND sp.country = $2)"
	}
	args = append(args, searchLimit)
	rows, err := s.db.Query(ctx, `SELECT u.name, '/staff/' || u.id, '' FROM "user" u
WHERE UPPER(u.name::text) LIKE UPPER($1) AND u.deleted_at IS NULL`+held+`
ORDER BY u.created_at DESC LIMIT $`+strconv.Itoa(len(args)), args...)
	if err != nil {
		return nil, fmt.Errorf("fieldpages: searching staff: %w", err)
	}
	return collect(rows, "staff")
}

// searchWork is list_activities({}) at a school or cluster of that name: a
// country reader's work in their country, anyone else's at their schools,
// under their staff id, or (a partner) their organisation's.
func (s *Service) searchWork(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, like string) ([]found, error) {
	args := []any{like}
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	reach := "true"
	if scope.CountryScope {
		if scope.Country != "" {
			reach = schoolprofile.ActivityInCountry(len(args) + 1)
			args = append(args, scope.CountryIDs())
		}
	} else {
		var held []string
		schools := scope.SchoolIDs
		var partners []string
		if slices.Contains(partnerRoles, p.ActiveRole) {
			// A partner's schools are those its organisation holds.
			ids, err := partnerassigned.PartnerIDs(ctx, s.db, p)
			if err != nil {
				return nil, err
			}
			partners, schools = ids, nil
			if len(ids) > 0 {
				held = append(held, "a.school_id IN (SELECT pa.school_id FROM partner_assignment pa WHERE pa.partner_id = ANY("+
					arg(ids)+") AND pa.status <> ALL("+arg(rules.PartnerReleasedStatuses)+"))")
			}
		}
		if len(schools) > 0 {
			held = append(held, "a.school_id = ANY("+arg(schools)+")")
		}
		if p.StaffProfileID != "" {
			held = append(held, "a.responsible_staff_id = "+arg(p.StaffProfileID))
		}
		if len(partners) > 0 {
			held = append(held, "a.assigned_partner_id = ANY("+arg(partners)+")")
		}
		reach = "false"
		if len(held) > 0 {
			reach = "(" + strings.Join(held, " OR ") + ")"
		}
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.fy, 'None'), COALESCE(a.quarter, 'None'),
  s.id IS NOT NULL, COALESCE(s.name, ''), cl.id IS NOT NULL, COALESCE(cl.name, '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.deleted_at IS NULL AND `+reach+`
  AND (UPPER(s.name::text) LIKE UPPER($1) OR UPPER(cl.name::text) LIKE UPPER($1))
ORDER BY a.created_at DESC LIMIT `+arg(searchLimit), args...)
	if err != nil {
		return nil, fmt.Errorf("fieldpages: searching activities: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (found, error) {
		var id, kind, status, fy, quarter, school, cluster string
		var hasSchool, hasCluster bool
		if err := r.Scan(&id, &kind, &status, &fy, &quarter, &hasSchool, &school, &hasCluster, &cluster); err != nil {
			return found{}, err
		}
		name := calendarpage.ActivityTypeLabel(kind)
		switch {
		case hasSchool:
			name += " — " + school
		case hasCluster:
			name += " — " + cluster
		}
		state, ok := rules.ActivityStatuses[status]
		if !ok {
			state = status
		}
		// The feed reads runs of white space as one, trimmed: an activity with
		// no year or quarter reads "· · Scheduled".
		return found{text: oneLine(name), href: "/activities/" + id, caption: oneLine(fy + " · " + quarter + " · " + state)}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("fieldpages: searching activities: %w", err)
	}
	return out, nil
}
