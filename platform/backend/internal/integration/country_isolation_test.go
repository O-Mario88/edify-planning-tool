//go:build integration

package integration

import (
	"context"
	"slices"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Edify Global, Phase 1 (docs/migration/80-multi-country-phase-0.md): the
// seed registers four countries with only Uganda Active, a Kenyan school
// never reaches a Ugandan reader, a school with no country reaches nobody,
// and a reader's country counts only while their account belongs to it.
// Every row it files starts "gcty" and is removed after.
func TestCountriesAreIsolated(t *testing.T) {
	ctx := context.Background()
	exec := func(sql string, args ...any) {
		t.Helper()
		if _, err := admin.Exec(ctx, sql, args...); err != nil {
			t.Fatalf("%s: %v", sql, err)
		}
	}
	clear := func() {
		for _, sql := range []string{
			`DELETE FROM country_registry.school_country WHERE school_id LIKE 'gcty%'`,
			`DELETE FROM country_registry.country_membership WHERE user_id LIKE 'gcty%'`,
			`DELETE FROM school WHERE id LIKE 'gcty%'`,
			`UPDATE country_registry.country SET state = 'draft', activated_on = NULL WHERE code = 'KE'`,
			`UPDATE country_registry.country_membership SET revoked_at = NULL, revoked_by = NULL WHERE revoked_by = 'gcty'`,
		} {
			if _, err := admin.Exec(ctx, sql); err != nil {
				t.Errorf("%s: %v", sql, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)

	// The seed: four countries, one Active.
	rows, err := admin.Query(ctx, `SELECT code || ':' || state FROM country_registry.country ORDER BY code`)
	if err != nil {
		t.Fatal(err)
	}
	states := []string{}
	for rows.Next() {
		var s string
		if err := rows.Scan(&s); err != nil {
			t.Fatal(err)
		}
		states = append(states, s)
	}
	rows.Close()
	if want := []string{"ET:draft", "KE:draft", "RW:draft", "UG:active"}; !slices.Equal(states, want) {
		t.Fatalf("countries %v, want %v", states, want)
	}

	// A Kenyan school, and a school no country holds: no region, no holder,
	// no explicit country.
	var base string
	if err := admin.QueryRow(ctx, `SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&base); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"gctyKE", "gctyNONE"} {
		exec(`INSERT INTO school SELECT (json_populate_record(NULL::school, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', $1::text, 'school_id', 'GCTY-' || $1::text, 'salesforce_account_id', NULL, 'region_id', NULL,
  'account_owner_id', NULL))::json)).* FROM school t WHERE id = $2`, id, base)
	}
	exec(`INSERT INTO country_registry.school_country (school_id, country_id, effective_from, source, recorded_by)
SELECT 'gctyKE', id, current_date, 'import', 'gcty' FROM country_registry.country WHERE code = 'KE'`)

	in := func(code string) []string {
		t.Helper()
		ids := []string{}
		rows, err := admin.Query(ctx, `SELECT s.id FROM school s WHERE s.id LIKE 'gcty%' AND `+
			country.SchoolIn("s", `ARRAY(SELECT id::text FROM country_registry.country WHERE code = $1)`)+` ORDER BY s.id`, code)
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				t.Fatal(err)
			}
			ids = append(ids, id)
		}
		return ids
	}
	if got := in("UG"); len(got) != 0 {
		t.Errorf("Uganda holds %v; the Kenyan school and the school of no country must be outside it", got)
	}
	if got := in("KE"); !slices.Equal(got, []string{"gctyKE"}) {
		t.Errorf("Kenya holds %v, want only its own school", got)
	}

	// The Country Director of Uganda: the directory's reach for them holds
	// every Ugandan school and neither of these.
	var cdUser, cdStaff string
	if err := admin.QueryRow(ctx, `SELECT u.id, sp.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.email = 'cd@edify.org'`).Scan(&cdUser, &cdStaff); err != nil {
		t.Fatal(err)
	}
	cd := auth.Principal{UserID: cdUser, StaffProfileID: cdStaff, ActiveRole: "CountryDirector", Roles: []string{"CountryDirector"}}
	reach := func() (int, []string) {
		t.Helper()
		scope, err := schooldirectory.ResolveScope(ctx, admin, cd, time.Now())
		if err != nil {
			t.Fatal(err)
		}
		args := []any{}
		where := schooldirectory.AnalyticsReach(scope, &args)
		var all int
		if err := admin.QueryRow(ctx, `SELECT count(*) FROM school s WHERE `+where, args...).Scan(&all); err != nil {
			t.Fatal(err)
		}
		ours := []string{}
		rows, err := admin.Query(ctx, `SELECT s.id FROM school s WHERE s.id LIKE 'gcty%' AND `+where, args...)
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				t.Fatal(err)
			}
			ours = append(ours, id)
		}
		return all, ours
	}
	var ugandan int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM school s WHERE s.deleted_at IS NULL AND EXISTS (
  SELECT 1 FROM country_registry.school_country sc JOIN country_registry.country c ON c.id = sc.country_id
  WHERE sc.school_id = s.id AND c.code = 'UG')`).Scan(&ugandan); err != nil {
		t.Fatal(err)
	}
	all, ours := reach()
	if len(ours) != 0 {
		t.Errorf("Uganda's Country Director reaches %v", ours)
	}
	if all != ugandan {
		t.Errorf("Uganda's Country Director reaches %d schools, want Uganda's %d", all, ugandan)
	}

	// Whose country counts: the profile's, while the account belongs to it.
	ids := func(user, name string) int {
		t.Helper()
		got, err := country.ReaderCountryIDs(ctx, admin, user, name)
		if err != nil {
			t.Fatal(err)
		}
		return len(got)
	}
	if ids(cdUser, "Uganda") != 1 {
		t.Error("Uganda's Country Director is not in Uganda")
	}
	if ids(cdUser, "Kenya") != 0 {
		t.Error("Uganda's Country Director reads Kenya")
	}
	if ids("gcty-nobody", "Uganda") != 1 {
		t.Error("an account with no membership at all does not keep its profile's country")
	}
	exec(`INSERT INTO country_registry.country_membership (id, user_id, country_id, is_default, effective_from, granted_by, grant_reason)
SELECT gen_random_uuid(), 'gcty-kenyan', id, true, current_date, 'gcty', 'isolation test' FROM country_registry.country WHERE code = 'KE'`)
	if ids("gcty-kenyan", "Uganda") != 0 {
		t.Error("an account that belongs to Kenya alone reads Uganda")
	}
	if ids("gcty-kenyan", "Kenya") != 0 {
		t.Error("a Draft country is worked in")
	}
	exec(`UPDATE country_registry.country SET state = 'active', activated_on = current_date WHERE code = 'KE'`)
	if ids("gcty-kenyan", "Kenya") != 1 {
		t.Error("an account that belongs to Active Kenya does not read it")
	}

	// A Country Director whose membership of Uganda is revoked reaches
	// nothing, rather than the whole platform an empty country would mean.
	exec(`UPDATE country_registry.country_membership SET revoked_at = now(), revoked_by = 'gcty' WHERE user_id = $1`, cdUser)
	if all, _ := reach(); all != 0 {
		t.Errorf("a Country Director with no membership of Uganda reaches %d schools", all)
	}
}
