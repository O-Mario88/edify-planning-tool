//go:build integration

package integration

import (
	"context"
	"slices"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
)

// The country through planning (docs/migration/80-multi-country-phase-0.md
// §13). With Kenya Active, an Impact Assessment officer who works in Kenya
// and a CCEO who works there: Team Plans shows Kenya's work to Kenya and
// Uganda's to Uganda, never the other's, including work at a Ugandan
// school with no region and no holder, which the existing rule put in every
// country; Kenya's roster holds the people who hold its roles and Uganda's
// no longer holds someone who left for Kenya; Kenya reads its own planning
// settings, of which it has none yet. The two accounts' memberships are taken
// away and put back exactly after; every other row starts "gcpl" and is
// removed, and Kenya is Draft again.
func TestTheCountryThroughPlanning(t *testing.T) {
	ctx := context.Background()
	exec := func(sql string, args ...any) {
		t.Helper()
		if _, err := admin.Exec(ctx, sql, args...); err != nil {
			t.Fatalf("%s: %v", sql, err)
		}
	}
	type account struct{ user, staff string }
	pick := func(skip string) account {
		t.Helper()
		var a account
		if err := admin.QueryRow(ctx, `SELECT u.id, sp.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
WHERE u.active_role = 'CCEO' AND u.is_active AND u.deleted_at IS NULL AND btrim(sp.country) = 'Uganda' AND u.id <> $1
  AND NOT EXISTS (SELECT 1 FROM staff_supervisor_assignment l JOIN staff_profile x ON x.id = l.supervisor_id
    JOIN "user" xu ON xu.id = x.user_id WHERE l.supervisee_id = sp.id AND 'ImpactAssessment' = ANY(xu.roles))
ORDER BY u.id LIMIT 1`, skip).Scan(&a.user, &a.staff); err != nil {
			t.Fatal(err)
		}
		return a
	}
	assessor := pick("")
	officer := pick(assessor.user)
	withoutMemberships(t, assessor.user)
	withoutMemberships(t, officer.user)
	clear := func() {
		for _, sql := range []string{
			`DELETE FROM country_registry.country_role_assignment WHERE user_id = ANY($1)`,
			`DELETE FROM country_registry.country_membership WHERE user_id = ANY($1)`,
			`DELETE FROM activity WHERE id LIKE 'gcpl%' AND $1::text[] IS NOT NULL`,
			`DELETE FROM country_registry.school_country WHERE school_id LIKE 'gcpl%' AND $1::text[] IS NOT NULL`,
			`DELETE FROM school WHERE id LIKE 'gcpl%' AND $1::text[] IS NOT NULL`,
			`UPDATE country_registry.country SET state = 'draft', activated_on = NULL WHERE code = 'KE' AND $1::text[] IS NOT NULL`,
		} {
			if _, err := admin.Exec(ctx, sql, []string{assessor.user, officer.user}); err != nil {
				t.Errorf("%s: %v", sql, err)
			}
		}
	}
	clear()
	// Registered after withoutMemberships, so it runs first.
	t.Cleanup(clear)

	// Kenya Active; both accounts belong to Kenya alone, the assessor as
	// Impact Assessment and the officer as CCEO.
	exec(`UPDATE country_registry.country SET state = 'active', activated_on = current_date WHERE code = 'KE'`)
	kenya := countryID(t, "KE")
	for _, a := range []struct{ user, role string }{{assessor.user, "ImpactAssessment"}, {officer.user, "CCEO"}} {
		exec(`WITH m AS (INSERT INTO country_registry.country_membership (id, user_id, country_id, is_default, effective_from, granted_by, grant_reason)
  VALUES (gen_random_uuid(), $1, $2::uuid, true, current_date, 'gcpl', 'Planning test') RETURNING id)
INSERT INTO country_registry.country_role_assignment (id, membership_id, country_id, user_id, role_name, scope_type, granted_by, grant_reason)
SELECT gen_random_uuid(), m.id, $2::uuid, $1, $3, $4, 'gcpl', 'Planning test' FROM m`,
			a.user, kenya, a.role, schooldirectory.ScopeTypeOf(a.role))
	}

	// A Kenyan school, and a Ugandan one with no region and no holder; work
	// at each, in this year, held by the officer.
	var baseSchool, baseActivity string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1),
  (SELECT id FROM activity WHERE deleted_at IS NULL AND school_id IS NOT NULL ORDER BY status = 'scheduled' DESC, id LIMIT 1)`).Scan(&baseSchool, &baseActivity); err != nil {
		t.Fatalf("a school and a school's activity to copy: %v", err)
	}
	fy := schooldirectory.OperationalFY(time.Now())
	for _, s := range []struct{ id, name, code string }{{"gcplKE", "Gcpl Kenyan School", "KE"}, {"gcplUG", "Gcpl Orphan School", "UG"}} {
		exec(`INSERT INTO school SELECT (json_populate_record(NULL::school, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', $1::text, 'school_id', 'GCPL-' || $1::text, 'name', $2::text, 'salesforce_account_id', NULL, 'region_id', NULL,
  'district_id', NULL, 'cluster_id', NULL, 'account_owner_id', NULL))::json)).* FROM school t WHERE id = $3`, s.id, s.name, baseSchool)
		exec(`INSERT INTO country_registry.school_country (school_id, country_id, effective_from, source, recorded_by)
SELECT $1, id, current_date, 'import', 'gcpl' FROM country_registry.country WHERE code = $2`, s.id, s.code)
		exec(`INSERT INTO activity SELECT (json_populate_record(NULL::activity, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcpl-' || $1::text, 'school_id', $1::text, 'cluster_id', NULL, 'fy', $2::text, 'status', 'scheduled',
  'responsible_staff_id', $3::text, 'monitored_by_staff_id', NULL, 'salesforce_activity_id', NULL,
  'paired_school_visit_id', NULL, 'follow_up_of_activity_id', NULL, 'daily_visit_batch_id', NULL,
  'deleted_at', NULL))::json)).* FROM activity t WHERE id = $4`, s.id, fy, officer.staff, baseActivity)
	}

	// Team Plans, filtered to the officer's work.
	var ugandaIA string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'ia@edify.org'`).Scan(&ugandaIA); err != nil {
		t.Fatal(err)
	}
	plans := func(user, role string) string {
		t.Helper()
		page, err := pageOf(token(t, user, role, time.Hour), adminops.TeamPlansPath, map[string]string{"user": officer.staff, "fy": fy})
		if err != nil {
			t.Fatalf("Team Plans as %s: %v", role, err)
		}
		return protojson.Format(page)
	}
	inKenya, inUganda := plans(assessor.user, "ImpactAssessment"), plans(ugandaIA, "ImpactAssessment")
	if !strings.Contains(inKenya, "Gcpl Kenyan School") || strings.Contains(inKenya, "Gcpl Orphan School") {
		t.Error("Kenya's Team Plans do not hold exactly Kenya's work")
	}
	if !strings.Contains(inUganda, "Gcpl Orphan School") || strings.Contains(inUganda, "Gcpl Kenyan School") {
		t.Error("Uganda's Team Plans do not hold exactly Uganda's work")
	}

	// The same rule as SQL: the existing one put the orphan in Kenya too.
	in := func(code string) []string {
		t.Helper()
		ids := []string{}
		rows, err := admin.Query(ctx, `SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.id LIKE 'gcpl%' AND `+country.ActivityIn("a", "s", "cl", "$1")+` ORDER BY a.id`, []string{countryID(t, code)})
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
	if got := in("KE"); !slices.Equal(got, []string{"gcpl-gcplKE"}) {
		t.Errorf("Kenya's work %v", got)
	}
	if got := in("UG"); !slices.Equal(got, []string{"gcpl-gcplUG"}) {
		t.Errorf("Uganda's work %v", got)
	}

	// Rosters: Kenya's Leads and CCEOs are those holding the roles there;
	// Uganda's no longer holds the officer, whose profile still says Uganda.
	roster := func(name, id string, fromRegistry bool) []string {
		t.Helper()
		r := country.RosterIn(name, id, fromRegistry, []string{"Program Lead", "CCEO"})
		rows, err := admin.Query(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.is_active AND u.deleted_at IS NULL AND `+r.Where+` ORDER BY sp.id`, r.Args...)
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		ids := []string{}
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				t.Fatal(err)
			}
			ids = append(ids, id)
		}
		return ids
	}
	if got := roster("Kenya", kenya, true); !slices.Equal(got, []string{officer.staff}) {
		t.Errorf("Kenya's roster %v, want the officer alone", got)
	}
	ugandans := roster("Uganda", countryID(t, "UG"), false)
	if slices.Contains(ugandans, officer.staff) || len(ugandans) == 0 {
		t.Errorf("Uganda's roster holds the officer who left for Kenya, or nobody (%d people)", len(ugandans))
	}

	// Settings: Kenya reads its own rows and finds none; Uganda's are read
	// as today.
	work, err := country.Working(ctx, admin, officer.user, "Uganda")
	if err != nil || work == nil || work.Code != "KE" {
		t.Fatalf("the officer works in %+v (%v), want Kenya", work, err)
	}
	if got := country.SettingsName(work, "Uganda"); got != "Kenya" {
		t.Errorf("Kenya's settings are keyed %q", got)
	}
	var kenyanCatalogue, ugandanCatalogue bool
	if err := admin.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cost_catalogue WHERE country = $1), EXISTS (SELECT 1 FROM cost_catalogue WHERE country = $2)`,
		country.SettingsName(work, "Uganda"), country.SettingsName(nil, "Uganda")).Scan(&kenyanCatalogue, &ugandanCatalogue); err != nil {
		t.Fatal(err)
	}
	if kenyanCatalogue || !ugandanCatalogue {
		t.Errorf("catalogues: Kenya %v, Uganda %v", kenyanCatalogue, ugandanCatalogue)
	}
	nairobi, _ := time.LoadLocation("Africa/Nairobi")
	if next, err := workplan.NextOpenFY(ctx, admin, work, time.Now(), nairobi); err != nil || next != "" {
		t.Errorf("Kenya's next planning year %q (%v): Uganda's planning calendar opened it", next, err)
	}
}
