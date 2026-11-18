//go:build integration

package integration

import (
	"context"
	"slices"
	"testing"
	"time"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// The country through partners (docs/migration/80-multi-country-phase-0.md
// §17). With Kenya Active, a Kenyan partner, a partner the existing
// application made after the seed (no recorded country), and an Impact
// Assessment officer who works in Kenya alone: a partner's country is the
// registry's, an unrecorded one Uganda's; country staff read and change only
// their own country's partner teams, while the Admin keeps every partner.
// Every row the test files starts "gcpt".
func TestTheCountryThroughPartners(t *testing.T) {
	ctx := context.Background()
	assessor, _, exec := twoKenyans(t, "gcpt")

	var basePartner, ugandaIA, adminID string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM partner WHERE deleted_at IS NULL AND id NOT LIKE 'gcpt%' ORDER BY id LIMIT 1),
  (SELECT id FROM "user" WHERE email = 'ia@edify.org'), (SELECT id FROM "user" WHERE email = 'admin@edify.org')`).Scan(&basePartner, &ugandaIA, &adminID); err != nil {
		t.Fatalf("a partner and readers to work with: %v", err)
	}
	for _, p := range []struct{ id, name string }{{"gcptKE", "Gcpt Kenyan Partner"}, {"gcptNEW", "Gcpt Unrecorded Partner"}} {
		exec(`INSERT INTO partner SELECT (json_populate_record(NULL::partner, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', $1::text, 'name', $2::text, 'user_id', NULL, 'loan_lender_id', NULL, 'email', $1::text || '@example.invalid'))::json)).*
FROM partner t WHERE id = $3`, p.id, p.name, basePartner)
	}
	exec(`INSERT INTO country_registry.partner_country (partner_id, country_id, effective_from, source, recorded_by)
SELECT 'gcptKE', id, current_date, 'import', 'gcpt' FROM country_registry.country WHERE code = 'KE'`)

	// The rule: recorded, else Uganda's.
	in := func(code string) []string {
		t.Helper()
		rows, err := admin.Query(ctx, `SELECT p.id FROM partner p WHERE p.deleted_at IS NULL AND `+country.PartnerIn("p", "$1")+` ORDER BY p.id`,
			[]string{countryID(t, code)})
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		out := []string{}
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				t.Fatal(err)
			}
			out = append(out, id)
		}
		return out
	}
	if got := in("KE"); !slices.Equal(got, []string{"gcptKE"}) {
		t.Errorf("Kenya's partners %v", got)
	}
	if got := in("UG"); slices.Contains(got, "gcptKE") || !slices.Contains(got, "gcptNEW") || !slices.Contains(got, basePartner) {
		t.Errorf("Uganda's partners %v", got)
	}

	// Partner teams through the gateway.
	team := func(user, role, partner string) error {
		_, err := partnerTeams().GetPartnerTeam(ctx, authed(&identityv1.GetPartnerTeamRequest{PartnerId: partner}, token(t, user, role, time.Hour)))
		return err
	}
	for _, c := range []struct {
		who, user, role, partner string
		allowed                  bool
	}{
		{"Kenya's IA, Kenya's partner", assessor.user, "ImpactAssessment", "gcptKE", true},
		{"Kenya's IA, a Ugandan partner", assessor.user, "ImpactAssessment", basePartner, false},
		{"Kenya's IA, an unrecorded partner", assessor.user, "ImpactAssessment", "gcptNEW", false},
		{"Uganda's IA, a Ugandan partner", ugandaIA, "ImpactAssessment", basePartner, true},
		{"Uganda's IA, an unrecorded partner", ugandaIA, "ImpactAssessment", "gcptNEW", true},
		{"Uganda's IA, Kenya's partner", ugandaIA, "ImpactAssessment", "gcptKE", false},
		{"the Admin, Kenya's partner", adminID, "Admin", "gcptKE", true},
		{"the Admin, a Ugandan partner", adminID, "Admin", basePartner, true},
	} {
		err := team(c.user, c.role, c.partner)
		if c.allowed && err != nil {
			t.Errorf("%s: %v", c.who, err)
		}
		if !c.allowed && connect.CodeOf(err) != connect.CodePermissionDenied {
			t.Errorf("%s: want refused, got %v", c.who, err)
		}
	}
	// Changing another country's partner team is refused, and writes nothing.
	_, err := partnerTeams().AddMember(ctx, authed(&identityv1.AddMemberRequest{PartnerId: basePartner, Name: "Gcpt Member",
		Role: "staff"}, token(t, assessor.user, "ImpactAssessment", time.Hour)))
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("Kenya's IA adding to a Ugandan partner's team: %v", err)
	}
	var added int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM partner_member WHERE name = 'Gcpt Member'`).Scan(&added); err != nil || added != 0 {
		t.Errorf("a refused member was written (%d, %v)", added, err)
	}
}
