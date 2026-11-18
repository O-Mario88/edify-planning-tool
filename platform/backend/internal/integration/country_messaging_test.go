//go:build integration

package integration

import (
	"context"
	"slices"
	"testing"
	"time"

	messagingv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1"
)

// The country through messages (docs/migration/80-multi-country-phase-0.md
// §21). A conversation about a school reaches only readers who may open
// that school: with Kenya Active, a Kenyan school, and an Impact
// Assessment officer who works in Kenya alone, Kenya's officer is shown the
// conversation about the Kenyan school and not one about a Ugandan school,
// and Uganda's officer the reverse. Every row the test files starts "gcms".
func TestTheCountryThroughMessages(t *testing.T) {
	ctx := context.Background()
	assessor, officer, exec := twoKenyans(t, "gcms")
	var ugandanSchool, ugandaIA string
	if err := admin.QueryRow(ctx, `SELECT (SELECT s.id FROM school s JOIN country_registry.school_country sc ON sc.school_id = s.id
    JOIN country_registry.country c ON c.id = sc.country_id AND c.code = 'UG' WHERE s.deleted_at IS NULL ORDER BY s.id LIMIT 1),
  (SELECT id FROM "user" WHERE email = 'ia@edify.org')`).Scan(&ugandanSchool, &ugandaIA); err != nil {
		t.Fatalf("a Ugandan school and Uganda's IA: %v", err)
	}
	exec(`INSERT INTO school SELECT (json_populate_record(NULL::school, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcmsKE', 'school_id', 'GCMS-KE', 'name', 'Gcms Kenyan School', 'salesforce_account_id', NULL, 'region_id', NULL,
  'district_id', NULL, 'cluster_id', NULL, 'account_owner_id', NULL))::json)).* FROM school t WHERE id = $1`, ugandanSchool)
	exec(`INSERT INTO country_registry.school_country (school_id, country_id, effective_from, source, recorded_by)
SELECT 'gcmsKE', id, current_date, 'import', 'gcms' FROM country_registry.country WHERE code = 'KE'`)

	seedThread(t, "gcmskeke0000001", "school", "gcmsKE", officer.user, assessor.user)
	seedThread(t, "gcmskeug0000001", "school", ugandanSchool, officer.user, assessor.user)
	seedThread(t, "gcmsugke0000001", "school", "gcmsKE", officer.user, ugandaIA)
	seedThread(t, "gcmsugug0000001", "school", ugandanSchool, officer.user, ugandaIA)

	listed := func(user string) []string {
		t.Helper()
		ids := []string{}
		for _, thread := range inboxOf(t, token(t, user, "ImpactAssessment", time.Hour), &messagingv1.ListThreadsRequest{}).GetThreads() {
			ids = append(ids, thread.GetId())
		}
		return ids
	}
	if got := listed(assessor.user); !slices.Contains(got, "gcmskeke0000001") || slices.Contains(got, "gcmskeug0000001") {
		t.Errorf("Kenya's officer is shown %v, want the Kenyan school's conversation and not the Ugandan one", got)
	}
	if got := listed(ugandaIA); !slices.Contains(got, "gcmsugug0000001") || slices.Contains(got, "gcmsugke0000001") {
		t.Errorf("Uganda's officer is shown %v, want the Ugandan school's conversation and not the Kenyan one", got)
	}
}
