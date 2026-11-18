//go:build integration

package integration

import (
	"context"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// kenyan is an existing account set to work in Kenya for a test.
type kenyan struct{ user, staff string }

// twoKenyans makes Kenya Active and moves two officers who work in Uganda
// today into Kenya alone: the assessor as Impact Assessment, the officer as
// CCEO. Their memberships are taken away and put back exactly after, every
// row whose id starts with prefix in the tables a country test files into is
// removed, and Kenya is Draft again. exec runs fixture SQL as the owner.
func twoKenyans(t *testing.T, prefix string) (assessor, officer kenyan, exec func(sql string, args ...any)) {
	t.Helper()
	ctx := context.Background()
	exec = func(sql string, args ...any) {
		t.Helper()
		if _, err := admin.Exec(ctx, sql, args...); err != nil {
			t.Fatalf("%s: %v", sql, err)
		}
	}
	pick := func(skip string) kenyan {
		t.Helper()
		var a kenyan
		if err := admin.QueryRow(ctx, `SELECT u.id, sp.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
WHERE u.active_role = 'CCEO' AND u.is_active AND u.deleted_at IS NULL AND btrim(sp.country) = 'Uganda' AND u.id <> $1
  AND NOT EXISTS (SELECT 1 FROM staff_supervisor_assignment l JOIN staff_profile x ON x.id = l.supervisor_id
    JOIN "user" xu ON xu.id = x.user_id WHERE l.supervisee_id = sp.id AND 'ImpactAssessment' = ANY(xu.roles))
ORDER BY u.id LIMIT 1`, skip).Scan(&a.user, &a.staff); err != nil {
			t.Fatal(err)
		}
		return a
	}
	assessor = pick("")
	officer = pick(assessor.user)
	withoutMemberships(t, assessor.user)
	withoutMemberships(t, officer.user)
	like := prefix + "%"
	clear := func() {
		for _, sql := range []string{
			`DELETE FROM country_registry.country_role_assignment WHERE user_id = ANY($1) AND $2 <> ''`,
			`DELETE FROM country_registry.country_membership WHERE user_id = ANY($1) AND $2 <> ''`,
			`DELETE FROM ssa_score WHERE ssa_record_id LIKE $2 AND $1::text[] IS NOT NULL`,
			`DELETE FROM ssa_record WHERE id LIKE $2 AND $1::text[] IS NOT NULL`,
			`DELETE FROM activity WHERE id LIKE $2 AND $1::text[] IS NOT NULL`,
			`DELETE FROM country_registry.school_country WHERE school_id LIKE $2 AND $1::text[] IS NOT NULL`,
			`DELETE FROM cluster WHERE id LIKE $2 AND $1::text[] IS NOT NULL`,
			`DELETE FROM school WHERE id LIKE $2 AND $1::text[] IS NOT NULL`,
			`DELETE FROM district WHERE id LIKE $2 AND $1::text[] IS NOT NULL`,
			`DELETE FROM region WHERE id LIKE $2 AND $1::text[] IS NOT NULL`,
			`UPDATE country_registry.country SET state = 'draft', activated_on = NULL WHERE code = 'KE' AND $1::text[] IS NOT NULL AND $2 <> ''`,
		} {
			if _, err := admin.Exec(ctx, sql, []string{assessor.user, officer.user}, like); err != nil {
				// Fatal: a role left behind keeps the memberships from being
				// put back.
				t.Fatalf("%s: %v", sql, err)
			}
		}
	}
	clear()
	// Registered after withoutMemberships, so it runs first: the roles go
	// before the memberships they name are put back.
	t.Cleanup(clear)

	exec(`UPDATE country_registry.country SET state = 'active', activated_on = current_date WHERE code = 'KE'`)
	kenya := countryID(t, "KE")
	for _, a := range []struct{ user, role string }{{assessor.user, "ImpactAssessment"}, {officer.user, "CCEO"}} {
		exec(`WITH m AS (INSERT INTO country_registry.country_membership (id, user_id, country_id, is_default, effective_from, granted_by, grant_reason)
  VALUES (gen_random_uuid(), $1, $2::uuid, true, current_date, $5, 'Country test') RETURNING id)
INSERT INTO country_registry.country_role_assignment (id, membership_id, country_id, user_id, role_name, scope_type, granted_by, grant_reason)
SELECT gen_random_uuid(), m.id, $2::uuid, $1, $3, $4, $5, 'Country test' FROM m`,
			a.user, kenya, a.role, schooldirectory.ScopeTypeOf(a.role), prefix)
	}
	return assessor, officer, exec
}
