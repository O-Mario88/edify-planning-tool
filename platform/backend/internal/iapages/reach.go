package iapages

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// reach is _ia_reach_q as a WHERE clause on activity `a` (its school `s` and
// cluster `cl` LEFT JOINed), its arguments appended to args: the reader's
// country (activity_country_q, when the scope is country-bound), and,
// without the IA verification permission, only the work an Impact
// Assessment officer (of that country, when there is one) is responsible
// for.
func reach(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, args []any) (string, []any, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", nil, fmt.Errorf("iapages: resolving the reader's scope: %w", err)
	}
	where := "TRUE"
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.Country)
		where = schoolprofile.ActivityInCountry(len(args))
	}
	if !slices.Contains(rules.IAVerifyRoles, p.ActiveRole) {
		officers := `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.roles @> ARRAY['ImpactAssessment']::varchar[] AND sp.deleted_at IS NULL`
		if scope.Country != "" {
			args = append(args, scope.Country)
			officers += fmt.Sprintf(" AND sp.country = $%d", len(args))
		}
		where = fmt.Sprintf("(%s) AND a.responsible_staff_id IN (%s)", where, officers)
	}
	return where, args, nil
}

// staffNames is verification_analytics._staff_names: each id's person's name
// (a live People record's account, else the record's own id), or for a
// legacy row holding an account id, that account's name.
func staffNames(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT sp.id, COALESCE(u.name, sp.id) FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) AND sp.deleted_at IS NULL
UNION ALL
SELECT u.id, u.name FROM "user" u WHERE u.id = ANY($1)
  AND u.id NOT IN (SELECT sp.id FROM staff_profile sp WHERE sp.id = ANY($1) AND sp.deleted_at IS NULL)`, ids)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the owners' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("iapages: reading the owners' names: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}
