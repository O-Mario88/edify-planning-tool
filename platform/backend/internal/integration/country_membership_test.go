//go:build integration

package integration

import (
	"context"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
)

// withoutMemberships takes every membership of userID away for the test and
// puts the rows back exactly as they were afterwards, so the account starts
// as one the existing application made after the registry was seeded.
func withoutMemberships(t *testing.T, userID string) {
	t.Helper()
	ctx := context.Background()
	rows, err := admin.Query(ctx, `SELECT to_jsonb(m)::text FROM country_registry.country_membership m WHERE m.user_id = $1`, userID)
	if err != nil {
		t.Fatal(err)
	}
	saved, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatal(err)
	}
	remove := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM country_registry.country_membership WHERE user_id = $1`, userID); err != nil {
			t.Fatal(err)
		}
	}
	remove()
	t.Cleanup(func() {
		remove()
		for _, row := range saved {
			if _, err := admin.Exec(ctx, `INSERT INTO country_registry.country_membership
SELECT * FROM jsonb_populate_record(NULL::country_registry.country_membership, $1::jsonb)`, row); err != nil {
				t.Error(err)
			}
		}
	})
}

// Membership management on CountryService: only an Admin grants and
// revokes, never their own; a grant may not quietly take away the country an
// account works in through its profile; overlapping grants are refused; a
// revocation keeps its record and its reason, and fails closed.
func TestCountryMemberships(t *testing.T) {
	ctx := context.Background()
	var adminID, cdID, officerID, profileCountry, today, month string
	if err := admin.QueryRow(ctx, `SELECT
  (SELECT id FROM "user" WHERE email = 'admin@edify.org'), (SELECT id FROM "user" WHERE email = 'cd@edify.org'),
  (SELECT u.id FROM "user" u WHERE u.active_role = 'CCEO' AND u.deleted_at IS NULL ORDER BY u.id DESC LIMIT 1),
  current_date::text, (current_date + 30)::text`).Scan(&adminID, &cdID, &officerID, &today, &month); err != nil {
		t.Fatal(err)
	}
	if err := admin.QueryRow(ctx, `SELECT COALESCE(max(country), '') FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL`,
		officerID).Scan(&profileCountry); err != nil || profileCountry != "Uganda" {
		t.Fatalf("the officer's profile names %q (%v), want Uganda", profileCountry, err)
	}
	withoutMemberships(t, officerID)

	asAdmin, asCD, asOfficer := token(t, adminID, "Admin", time.Hour), token(t, cdID, "CountryDirector", time.Hour),
		token(t, officerID, "CCEO", time.Hour)
	client := countriesClient()
	list := func(bearer, userID string) ([]*countriesv1.Membership, error) {
		got, err := client.ListMemberships(ctx, authed(&countriesv1.ListMembershipsRequest{UserId: userID}, bearer))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetMemberships(), nil
	}
	grant := func(bearer string, r *countriesv1.GrantMembershipRequest) (*countriesv1.Membership, error) {
		got, err := client.GrantMembership(ctx, authed(r, bearer))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetGranted(), nil
	}
	revoke := func(bearer, id, reason string) (*countriesv1.Membership, error) {
		got, err := client.RevokeMembership(ctx, authed(&countriesv1.RevokeMembershipRequest{MembershipId: id, Reason: reason}, bearer))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetRevoked(), nil
	}
	ask := func(userID, code, from, until string) *countriesv1.GrantMembershipRequest {
		return &countriesv1.GrantMembershipRequest{UserId: userID, CountryCode: code, EffectiveFrom: from,
			EffectiveUntil: until, Reason: "Membership test"}
	}
	countries := func(bearer string) []string {
		t.Helper()
		got, err := client.ListCountries(ctx, authed(&countriesv1.ListCountriesRequest{}, bearer))
		if err != nil {
			t.Fatal(err)
		}
		out := []string{}
		for _, c := range got.Msg.GetCountries() {
			out = append(out, c.GetCode())
		}
		return out
	}

	// Reading: an account reads its own; only an Admin reads another's.
	_, err := list("", "")
	requireCode(t, err, connect.CodeUnauthenticated, "")
	_, err = list(asCD, officerID)
	requireCode(t, err, connect.CodePermissionDenied, "")
	mine, err := list(asCD, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(mine) != 1 || mine[0].GetCountryCode() != "UG" || !mine[0].GetInForce() || !mine[0].GetIsDefault() {
		t.Errorf("the Country Director's memberships %+v, want Uganda in force", mine)
	}
	if got, err := list(asOfficer, ""); err != nil || len(got) != 0 {
		t.Errorf("the officer's memberships %+v (%v), want none", got, err)
	}
	if got := countries(asOfficer); len(got) != 1 || got[0] != "UG" {
		t.Errorf("an officer with no membership works in %v, want Uganda through the profile", got)
	}

	// Who may grant, and what is refused before anything is written.
	_, err = grant(asCD, ask(officerID, "UG", "", ""))
	requireCode(t, err, connect.CodePermissionDenied, "")
	_, err = grant(asAdmin, ask(adminID, "KE", "", ""))
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	noReason := ask(officerID, "UG", "", "")
	noReason.Reason = " "
	_, err = grant(asAdmin, noReason)
	requireCode(t, err, connect.CodeInvalidArgument, "")
	_, err = grant(asAdmin, ask(officerID, "UG", "1 March 2026", ""))
	requireCode(t, err, connect.CodeInvalidArgument, "")
	_, err = grant(asAdmin, ask(officerID, "UG", month, today))
	requireCode(t, err, connect.CodeInvalidArgument, "")
	_, err = grant(asAdmin, ask(officerID, "UG", "2020-01-01", ""))
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	_, err = grant(asAdmin, ask(officerID, "ZZ", "", ""))
	requireCode(t, err, connect.CodeNotFound, "")
	_, err = grant(asAdmin, ask("no-such-account", "UG", "", ""))
	requireCode(t, err, connect.CodeNotFound, "")
	// Kenya first would end the officer's Uganda, which they hold through
	// their profile alone.
	_, err = grant(asAdmin, ask(officerID, "KE", "", ""))
	requireCode(t, err, connect.CodeFailedPrecondition, "")

	uganda, err := grant(asAdmin, ask(officerID, "UG", "", ""))
	if err != nil {
		t.Fatal(err)
	}
	if uganda.GetCountryCode() != "UG" || uganda.GetUserId() != officerID || uganda.GetEffectiveFrom() != today ||
		uganda.GetGrantedBy() != adminID || uganda.GetGrantReason() != "Membership test" || !uganda.GetIsDefault() ||
		!uganda.GetInForce() {
		t.Errorf("Uganda granted %+v", uganda)
	}
	_, err = grant(asAdmin, ask(officerID, "UG", month, ""))
	requireCode(t, err, connect.CodeFailedPrecondition, "")

	kenya, err := grant(asAdmin, ask(officerID, "KE", "", month))
	if err != nil {
		t.Fatal(err)
	}
	if kenya.GetIsDefault() || kenya.GetInForce() || kenya.GetCountryState() != "draft" || kenya.GetEffectiveUntil() != month {
		t.Errorf("Kenya (Draft) granted %+v, want not default and not in force", kenya)
	}
	if got := countries(asOfficer); len(got) != 1 || got[0] != "UG" {
		t.Errorf("with a Draft Kenya the officer works in %v, want Uganda", got)
	}

	// Revoking.
	_, err = revoke(asCD, kenya.GetId(), "Membership test")
	requireCode(t, err, connect.CodePermissionDenied, "")
	_, err = revoke(asAdmin, kenya.GetId(), "")
	requireCode(t, err, connect.CodeInvalidArgument, "")
	_, err = revoke(asAdmin, "not-a-membership", "Membership test")
	requireCode(t, err, connect.CodeInvalidArgument, "")
	_, err = revoke(asAdmin, "00000000-0000-0000-0000-000000000000", "Membership test")
	requireCode(t, err, connect.CodeNotFound, "")
	adminsOwn, err := list(asAdmin, adminID)
	if err != nil || len(adminsOwn) == 0 {
		t.Fatalf("the Admin's memberships %+v (%v)", adminsOwn, err)
	}
	_, err = revoke(asAdmin, adminsOwn[0].GetId(), "Membership test")
	requireCode(t, err, connect.CodeFailedPrecondition, "")

	revoked, err := revoke(asAdmin, kenya.GetId(), "Kenya pilot postponed")
	if err != nil {
		t.Fatal(err)
	}
	if revoked.GetRevokedBy() != adminID || revoked.GetRevokeReason() != "Kenya pilot postponed" || revoked.GetRevokedAt() == "" ||
		revoked.GetInForce() {
		t.Errorf("Kenya revoked %+v", revoked)
	}
	_, err = revoke(asAdmin, kenya.GetId(), "Membership test")
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	// A revoked grant keeps its date: a new one starts another day.
	_, err = grant(asAdmin, ask(officerID, "KE", "", ""))
	requireCode(t, err, connect.CodeFailedPrecondition, "")

	// Revoking the last country fails closed: the profile does not give it
	// back.
	if _, err := revoke(asAdmin, uganda.GetId(), "Left Edify Uganda"); err != nil {
		t.Fatal(err)
	}
	if got := countries(asOfficer); len(got) != 0 {
		t.Errorf("with every membership revoked the officer works in %v, want none", got)
	}
	history, err := list(asOfficer, "")
	if err != nil || len(history) != 2 || history[0].GetCountryCode() != "KE" || history[1].GetRevokeReason() != "Left Edify Uganda" {
		t.Errorf("the officer's history %+v (%v), want Kenya then Uganda, both kept", history, err)
	}

	// The table itself refuses a revocation without a reason.
	if _, err := admin.Exec(ctx, `UPDATE country_registry.country_membership SET revoke_reason = NULL
WHERE id = $1::uuid`, uganda.GetId()); err == nil {
		t.Error("a revocation without a reason was accepted by the table")
	}
}
