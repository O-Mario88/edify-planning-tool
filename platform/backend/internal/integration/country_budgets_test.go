//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The country through budgets (docs/migration/80-multi-country-phase-0.md
// §18). With Kenya Active and keeping its money in KES, a Kenyan school
// with one planned cost line, and an Impact Assessment officer who works in
// Kenya alone: Kenya's country Budget holds exactly Kenya's line, in KES,
// and none of Uganda's money; Kenya reads its own rate card (none yet) while
// Uganda's card is read as today. Every row the test files starts "gcbd".
func TestTheCountryThroughBudgets(t *testing.T) {
	ctx := context.Background()
	assessor, officer, exec := twoKenyans(t, "gcbd")
	// Kenya's settings: Kenyan shillings (the cleanup removes the version by
	// its reason, "gcbd%").
	exec(`INSERT INTO country_registry.country_config_version
  (id, country_id, version, default_language, languages, currency_code, currency_minor_units, time_zone, date_format,
   calendars, fy_start_month, effective_from, changed_by, change_reason)
SELECT gen_random_uuid(), id, 1, 'en', '{en,sw}', 'KES', 0, 'Africa/Nairobi', 'j M Y', '{gregorian}', 7, current_date - 1, 'gcbd', 'gcbd settings'
FROM country_registry.country WHERE code = 'KE'`)

	var baseSchool, baseActivity string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1),
  (SELECT id FROM activity WHERE deleted_at IS NULL AND school_id IS NOT NULL ORDER BY status = 'scheduled' DESC, id LIMIT 1)`).Scan(&baseSchool, &baseActivity); err != nil {
		t.Fatalf("a school and an activity to copy: %v", err)
	}
	now := time.Now()
	fy := schooldirectory.OperationalFY(now)
	exec(`INSERT INTO school SELECT (json_populate_record(NULL::school, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcbdKE', 'school_id', 'GCBD-KE', 'name', 'Gcbd Kenyan School', 'salesforce_account_id', NULL, 'region_id', NULL,
  'district_id', NULL, 'cluster_id', NULL, 'account_owner_id', NULL))::json)).* FROM school t WHERE id = $1`, baseSchool)
	exec(`INSERT INTO country_registry.school_country (school_id, country_id, effective_from, source, recorded_by)
SELECT 'gcbdKE', id, current_date, 'import', 'gcbd' FROM country_registry.country WHERE code = 'KE'`)
	exec(`INSERT INTO activity SELECT (json_populate_record(NULL::activity, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcbd-act', 'school_id', 'gcbdKE', 'cluster_id', NULL, 'fy', $1::text, 'status', 'scheduled',
  'planned_date', current_date, 'responsible_staff_id', $2::text, 'monitored_by_staff_id', NULL, 'salesforce_activity_id', NULL,
  'paired_school_visit_id', NULL, 'follow_up_of_activity_id', NULL, 'daily_visit_batch_id', NULL, 'deleted_at', NULL))::json)).*
FROM activity t WHERE id = $3`, fy, officer.staff, baseActivity)
	exec(`INSERT INTO activity_schedule_cost_line (created_at, updated_at, id, cost_setting_key, label, unit_cost, quantity, amount,
  cost_setting_version, activity_id, currency, fiscal_year, month, planned_date, responsible_user, school_id, vendor_paid)
VALUES (now(), now(), 'gcbd-line', 'transport', 'Gcbd transport', 12345, 1, 12345, 1, 'gcbd-act', 'KES', $1,
  extract(month FROM current_date)::int, current_date, $2, 'gcbdKE', false)`, fy, officer.user)

	page, err := pageOf(token(t, assessor.user, "ImpactAssessment", time.Hour), budgetpage.Path, map[string]string{"period": "fy", "fy": fy})
	if err != nil {
		t.Fatalf("Kenya's Budget: %v", err)
	}
	kenyan := protojson.Format(page)
	if !strings.Contains(kenyan, "Grand total") || !strings.Contains(kenyan, "KES 12,345") {
		t.Error("Kenya's Budget does not total Kenya's line in KES")
	}
	if strings.Contains(kenyan, "UGX") {
		t.Error("Kenya's Budget shows money in UGX")
	}

	// The rate card is the request's country's: Kenya has none recorded.
	work, err := country.Working(ctx, admin, assessor.user, "Uganda")
	if err != nil || work == nil || work.Code != "KE" {
		t.Fatalf("the assessor works in %+v (%v)", work, err)
	}
	if code, err := country.CurrencyOf(ctx, admin, work); err != nil || code != "KES" {
		t.Errorf("Kenya's currency %q (%v)", code, err)
	}
	var kenyanCards, ugandanCards int
	if err := admin.QueryRow(ctx, `SELECT (SELECT count(*) FROM cost_catalogue WHERE country = $1), (SELECT count(*) FROM cost_catalogue WHERE country = $2)`,
		country.SettingsName(work, "Uganda"), country.SettingsName(nil, "Uganda")).Scan(&kenyanCards, &ugandanCards); err != nil {
		t.Fatal(err)
	}
	if kenyanCards != 0 || ugandanCards == 0 {
		t.Errorf("rate cards: Kenya %d, Uganda %d", kenyanCards, ugandanCards)
	}
}
