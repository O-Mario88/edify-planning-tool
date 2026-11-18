//go:build integration

package integration

import (
	"context"
	"slices"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Role and scope per country (docs/migration/80-multi-country-phase-0.md
// §12). Uganda's roles stay each account's profile; in Kenya an account
// works only in the roles an Admin assigned it there (never a regional role,
// which works across every country), with that role's
// scope, and with none it is refused. The officer's memberships are taken
// away for the test and put back exactly after; every other row it files
// starts "gcrl" and is removed, and Kenya is Draft again.
func TestCountryRoles(t *testing.T) {
	ctx := context.Background()
	var adminID, cdID, officerID, officerStaff, ugRegion string
	if err := admin.QueryRow(ctx, `SELECT
  (SELECT id FROM "user" WHERE email = 'admin@edify.org'), (SELECT id FROM "user" WHERE email = 'cd@edify.org'),
  u.id, sp.id, (SELECT r.id FROM region r WHERE r.country = 'Uganda' ORDER BY r.id LIMIT 1)
FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
WHERE u.active_role = 'CCEO' AND u.deleted_at IS NULL AND btrim(sp.country) = 'Uganda'
  AND EXISTS (SELECT 1 FROM staff_school_assignment a WHERE a.staff_id = sp.id)
ORDER BY u.id DESC LIMIT 1`).Scan(&adminID, &cdID, &officerID, &officerStaff, &ugRegion); err != nil {
		t.Fatal(err)
	}
	withoutMemberships(t, officerID)
	exec := func(sql string, args ...any) {
		t.Helper()
		if _, err := admin.Exec(ctx, sql, args...); err != nil {
			t.Fatalf("%s: %v", sql, err)
		}
	}
	clear := func() {
		for _, sql := range []string{
			`DELETE FROM country_registry.country_role_assignment WHERE user_id = $1`,
			`DELETE FROM region WHERE id LIKE 'gcrl%' AND $1 <> ''`,
			`UPDATE country_registry.country SET state = 'draft', activated_on = NULL WHERE code = 'KE' AND $1 <> ''`,
		} {
			if _, err := admin.Exec(ctx, sql, officerID); err != nil {
				t.Errorf("%s: %v", sql, err)
			}
		}
	}
	clear()
	// Registered after withoutMemberships, so it runs first: the roles go
	// before the memberships they name are put back.
	t.Cleanup(clear)
	exec(`INSERT INTO region SELECT (json_populate_record(NULL::region, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcrlKE', 'name', 'Gcrl Nairobi', 'country', 'Kenya'))::json)).* FROM region t WHERE id = $1`, ugRegion)

	asAdmin, asCD := token(t, adminID, "Admin", time.Hour), token(t, cdID, "CountryDirector", time.Hour)
	asOfficer := token(t, officerID, "CCEO", time.Hour)
	client := countriesClient()
	grant := func(code string) *countriesv1.Membership {
		t.Helper()
		got, err := client.GrantMembership(ctx, authed(&countriesv1.GrantMembershipRequest{UserId: officerID, CountryCode: code,
			Reason: "Country roles test"}, asAdmin))
		if err != nil {
			t.Fatalf("granting %s: %v", code, err)
		}
		return got.Msg.GetGranted()
	}
	assign := func(bearer, membership, role string, regions ...string) (*countriesv1.Membership, error) {
		got, err := client.AssignCountryRole(ctx, authed(&countriesv1.AssignCountryRoleRequest{MembershipId: membership, Role: role,
			RegionIds: regions, Reason: "Country roles test"}, bearer))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetMembership(), nil
	}
	revokeRole := func(id, reason string) (*countriesv1.Membership, error) {
		got, err := client.RevokeCountryRole(ctx, authed(&countriesv1.RevokeCountryRoleRequest{RoleId: id, Reason: reason}, asAdmin))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetMembership(), nil
	}
	session := func() (*identityv1.Session, error) {
		got, err := identityClient().GetSession(ctx, authed(&identityv1.GetSessionRequest{}, asOfficer))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetSession(), nil
	}

	uganda, kenya := grant("UG"), grant("KE")
	if uganda.GetRolesSource() != country.RolesFromProfile || kenya.GetRolesSource() != country.RolesFromRegistry {
		t.Fatalf("roles sources: Uganda %q, Kenya %q", uganda.GetRolesSource(), kenya.GetRolesSource())
	}

	// What an Admin is offered: every role but Admin, and Kenya's regions.
	listed, err := client.ListMemberships(ctx, authed(&countriesv1.ListMembershipsRequest{UserId: officerID}, asAdmin))
	if err != nil {
		t.Fatal(err)
	}
	offered := []string{}
	for _, r := range listed.Msg.GetAssignableRoles() {
		offered = append(offered, r.GetRole())
	}
	if !slices.Contains(offered, "CCEO") || slices.Contains(offered, "Admin") {
		t.Errorf("roles offered %v", offered)
	}
	if regions := listed.Msg.GetRegions(); len(regions) != 1 || regions[0].GetId() != "gcrlKE" || regions[0].GetCountryCode() != "KE" {
		t.Errorf("regions offered %+v, want Kenya's one", regions)
	}

	// Who may assign, and what is refused.
	_, err = assign(asCD, kenya.GetId(), "CCEO")
	requireCode(t, err, connect.CodePermissionDenied, "")
	var adminUganda string
	if err := admin.QueryRow(ctx, `SELECT id::text FROM country_registry.country_membership WHERE user_id = $1 AND revoked_at IS NULL LIMIT 1`,
		adminID).Scan(&adminUganda); err != nil {
		t.Fatal(err)
	}
	_, err = assign(asAdmin, adminUganda, "CCEO")
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	_, err = assign(asAdmin, uganda.GetId(), "CCEO")
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	_, err = assign(asAdmin, kenya.GetId(), "Admin")
	requireCode(t, err, connect.CodeInvalidArgument, "")
	// The regional roles work across every country (owner, 2026-11-18):
	// none is assigned in one.
	for _, role := range []string{"RegionalVicePresident", "HumanResources", "RegionalProgramLead", "BusinessTransformationOfficer"} {
		_, err = assign(asAdmin, kenya.GetId(), role, "gcrlKE")
		requireCode(t, err, connect.CodeInvalidArgument, "")
	}
	_, err = assign(asAdmin, "00000000-0000-4000-8000-000000000000", "CCEO")
	requireCode(t, err, connect.CodeNotFound, "")

	// A role in Kenya, then a second; the same role twice is refused.
	got, err := assign(asAdmin, kenya.GetId(), "CCEO")
	if err != nil {
		t.Fatal(err)
	}
	if roles := got.GetRoles(); len(roles) != 1 || roles[0].GetRole() != "CCEO" || roles[0].GetScopeType() != country.ScopePortfolio ||
		roles[0].GetGrantedBy() != adminID {
		t.Fatalf("Kenya's roles %+v", roles)
	}
	officerRole := got.GetRoles()[0].GetId()
	_, err = assign(asAdmin, kenya.GetId(), "CCEO")
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	got, err = assign(asAdmin, kenya.GetId(), "ImpactAssessment")
	if err != nil {
		t.Fatal(err)
	}
	if r := got.GetRoles()[0]; r.GetRole() != "ImpactAssessment" || r.GetScopeType() != country.ScopeCountry {
		t.Errorf("the second role %+v", r)
	}

	// While the officer works in Uganda (the default, Active), the profile
	// decides: nothing assigned in Kenya applies.
	s, err := session()
	if err != nil || s.GetActiveRole() != "CCEO" || slices.Contains(s.GetRoles(), "ImpactAssessment") {
		t.Fatalf("in Uganda: %+v (%v)", s, err)
	}

	// Kenya Active and Uganda revoked: the officer works in Kenya, in the
	// roles assigned there.
	exec(`UPDATE country_registry.country SET state = 'active', activated_on = current_date WHERE code = 'KE'`)
	if _, err := client.RevokeMembership(ctx, authed(&countriesv1.RevokeMembershipRequest{MembershipId: uganda.GetId(),
		Reason: "Moves to Kenya"}, asAdmin)); err != nil {
		t.Fatal(err)
	}
	s, err = session()
	if err != nil || s.GetActiveRole() != "CCEO" || !slices.Equal(s.GetRoles(), []string{"CCEO", "ImpactAssessment"}) {
		t.Fatalf("in Kenya: %+v (%v), want CCEO and Impact Assessment", s, err)
	}

	// The scope is Kenya's: the officer's portfolio in the existing tables
	// (Ugandan schools) is not theirs there.
	work, err := country.Working(ctx, admin, officerID, "Uganda")
	if err != nil || work == nil || work.Code != "KE" {
		t.Fatalf("the working country %+v (%v)", work, err)
	}
	principal := func(role string) auth.Principal {
		return auth.Principal{Account: auth.Account{UserID: officerID, StaffProfileID: officerStaff, ActiveRole: role,
			Roles: []string{"CCEO", "ImpactAssessment", "RegionalProgramLead"}, Country: work}}
	}
	scope, err := schooldirectory.ResolveScope(ctx, admin, principal("CCEO"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if len(scope.OwnSchoolIDs) != 0 || len(scope.SchoolIDs) != 0 {
		t.Errorf("as Kenya's officer the portfolio holds %d own and %d schools, want none of Uganda's",
			len(scope.OwnSchoolIDs), len(scope.SchoolIDs))
	}
	scope, err = schooldirectory.ResolveScope(ctx, admin, principal("ImpactAssessment"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if scope.Country != "Kenya" || !scope.CountryFromRegistry {
		t.Errorf("as Kenya's Impact Assessment the country is %q (registry %v)", scope.Country, scope.CountryFromRegistry)
	}
	// A regional role, from the profile, reaches every country's regions,
	// even while the account works in Kenya.
	scope, err = schooldirectory.ResolveScope(ctx, admin, principal("RegionalProgramLead"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Contains(scope.RegionIDs, "gcrlKE") || !slices.Contains(scope.RegionIDs, ugRegion) || scope.Country != "" {
		t.Errorf("a regional lead reaches %v (country %q), want Kenya's and Uganda's regions", scope.RegionIDs, scope.Country)
	}

	// Revoking: a reason is required, the record is kept, and with no role
	// left in Kenya the officer is refused rather than given the profile's.
	_, err = revokeRole(officerRole, "")
	requireCode(t, err, connect.CodeInvalidArgument, "")
	got, err = revokeRole(officerRole, "Officer moved on")
	if err != nil {
		t.Fatal(err)
	}
	if r := got.GetRoles()[1]; r.GetId() != officerRole || r.GetRevokedBy() != adminID || r.GetRevokeReason() != "Officer moved on" {
		t.Errorf("the revoked role %+v", r)
	}
	_, err = revokeRole(officerRole, "Again")
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	if _, err := revokeRole(got.GetRoles()[0].GetId(), "No assessment work yet"); err != nil {
		t.Fatal(err)
	}
	_, err = session()
	requireCode(t, err, connect.CodePermissionDenied, "")

	// The table itself: a role filed against another country's membership,
	// or written for a country the transaction did not declare, is refused.
	if _, err := admin.Exec(ctx, `INSERT INTO country_registry.country_role_assignment
  (id, membership_id, country_id, user_id, role_name, scope_type, granted_by, grant_reason)
VALUES (gen_random_uuid(), $1::uuid, $2::uuid, $3, 'CCEO', 'portfolio', 'gcrl', 'mismatch')`,
		kenya.GetId(), countryID(t, "UG"), officerID); err == nil {
		t.Error("a role whose country is not its membership's was filed")
	}
	if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error {
		if err := country.WriteFor(ctx, tx, false, countryID(t, "UG")); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `INSERT INTO country_registry.country_role_assignment
  (id, membership_id, country_id, user_id, role_name, scope_type, granted_by, grant_reason)
VALUES (gen_random_uuid(), $1::uuid, $2::uuid, $3, 'CCEO', 'portfolio', 'gcrl', 'undeclared')`,
			kenya.GetId(), countryID(t, "KE"), officerID)
		return err
	}); !refusedByRowSecurity(err) {
		t.Errorf("a Kenyan role written in a transaction declared for Uganda: %v", err)
	}
}
