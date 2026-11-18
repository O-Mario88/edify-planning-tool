//go:build integration

package integration

import (
	"context"
	"slices"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ssaverify"
)

// The country through SSA (docs/migration/80-multi-country-phase-0.md §14).
// With Kenya Active and an Impact Assessment officer and a CCEO who work in
// Kenya alone: the SSA verification queue shows Kenya's records to Kenya and
// Uganda's to Uganda, never the other's, including a record at a Ugandan
// school with no region and no holder, which the existing rule put in every
// country; a school's SSA change rules are its registry country's; Kenya's
// regions and people are its own. Every row the test files starts "gcss".
func TestTheCountryThroughSSA(t *testing.T) {
	ctx := context.Background()
	assessor, officer, exec := twoKenyans(t, "gcss")
	assessorUser := assessor.user

	// A Kenyan region; a Kenyan school, and a Ugandan one with no region and
	// no holder; a pending SSA at each, collected by the officer.
	var baseSchool, baseRegion string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1),
  (SELECT id FROM region ORDER BY id LIMIT 1)`).Scan(&baseSchool, &baseRegion); err != nil {
		t.Fatalf("a school and a region to copy: %v", err)
	}
	exec(`INSERT INTO region SELECT (json_populate_record(NULL::region, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcssRG', 'name', 'Gcss Nairobi', 'country', 'Kenya'))::json)).* FROM region t WHERE id = $1`, baseRegion)
	for _, s := range []struct{ id, name, code string }{{"gcssKE", "Gcss Kenyan School", "KE"}, {"gcssUG", "Gcss Orphan School", "UG"}} {
		exec(`INSERT INTO school SELECT (json_populate_record(NULL::school, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', $1::text, 'school_id', 'GCSS-' || $1::text, 'name', $2::text, 'salesforce_account_id', NULL, 'region_id', NULL,
  'district_id', NULL, 'cluster_id', NULL, 'account_owner_id', NULL))::json)).* FROM school t WHERE id = $3`, s.id, s.name, baseSchool)
		exec(`INSERT INTO country_registry.school_country (school_id, country_id, effective_from, source, recorded_by)
SELECT $1, id, current_date, 'import', 'gcss' FROM country_registry.country WHERE code = $2`, s.id, s.code)
		exec(`INSERT INTO ssa_record (created_at, updated_at, id, date_of_ssa, fy, quarter, average_score, verification_status,
  collector_type, collected_by_user_id, uploaded_by, school_id, environment, source, return_reason)
VALUES (now(), now(), 'gcss-' || $1::text, now(), '2027', 'Q1', 3.5, 'pending', 'staff', $2, $2, $1, 'production', 'gcss', '')`,
			s.id, officer.user)
	}

	// The verification queue.
	var ugandaIA string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'ia@edify.org'`).Scan(&ugandaIA); err != nil {
		t.Fatal(err)
	}
	queue := func(user string) string {
		t.Helper()
		page, err := pageOf(token(t, user, "ImpactAssessment", time.Hour), ssaverify.Path, map[string]string{"status": "pending"})
		if err != nil {
			t.Fatalf("the SSA queue: %v", err)
		}
		return protojson.Format(page)
	}
	inKenya, inUganda := queue(assessorUser), queue(ugandaIA)
	if !strings.Contains(inKenya, "Gcss Kenyan School") || strings.Contains(inKenya, "Gcss Orphan School") {
		t.Error("Kenya's SSA queue does not hold exactly Kenya's records")
	}
	if !strings.Contains(inUganda, "Gcss Orphan School") || strings.Contains(inUganda, "Gcss Kenyan School") {
		t.Error("Uganda's SSA queue does not hold exactly Uganda's records")
	}

	// The country whose SSA change rules apply: the registry's.
	names := map[string]string{}
	rows, err := admin.Query(ctx, `SELECT s.id, `+country.SchoolCountryName("s")+` FROM school s WHERE s.id LIKE 'gcss%'`)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			t.Fatal(err)
		}
		names[id] = name
	}
	rows.Close()
	if names["gcssKE"] != "Kenya" || names["gcssUG"] != "Uganda" {
		t.Errorf("the schools' countries %v", names)
	}

	// Kenya's regions and people are its own; Uganda's no longer include
	// the officer who left for Kenya.
	collect := func(sql string, args ...any) []string {
		t.Helper()
		rows, err := admin.Query(ctx, sql, args...)
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		out := []string{}
		for rows.Next() {
			var id *string
			if err := rows.Scan(&id); err != nil {
				t.Fatal(err)
			}
			if id != nil {
				out = append(out, *id)
			}
		}
		return out
	}
	kenya, uganda := countryID(t, "KE"), countryID(t, "UG")
	if got := collect(`SELECT id FROM region WHERE id IN `+country.RegionsIn("$1")+` ORDER BY id`, []string{kenya}); !slices.Equal(got, []string{"gcssRG"}) {
		t.Errorf("Kenya's regions %v", got)
	}
	if got := collect(`SELECT id FROM region WHERE id IN `+country.RegionsIn("$1")+` ORDER BY id`, []string{uganda}); slices.Contains(got, "gcssRG") || len(got) == 0 {
		t.Errorf("Uganda's regions %v", got)
	}
	kenyans := collect(`SELECT * FROM `+country.UsersIn("$1::text")+` x ORDER BY 1`, kenya)
	if !slices.Contains(kenyans, officer.user) || !slices.Contains(kenyans, assessorUser) || len(kenyans) != 2 {
		t.Errorf("Kenya's people %v, want the two who work there", kenyans)
	}
	ugandans := collect(`SELECT * FROM `+country.UsersIn("$1::text")+` x`, uganda)
	if slices.Contains(ugandans, officer.user) || len(ugandans) == 0 {
		t.Errorf("Uganda's people hold the officer who left for Kenya, or nobody (%d)", len(ugandans))
	}
}
