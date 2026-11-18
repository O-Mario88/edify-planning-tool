//go:build integration

package integration

import (
	"context"
	"net/http"
	"slices"
	"testing"
	"time"

	"connectrpc.com/connect"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
)

// The country through loans (docs/migration/80-multi-country-phase-0.md
// §20). With Kenya Active, a lender recorded in Kenya, another left as the
// existing application made it (so Uganda's), a school loan application not
// yet matched to a school (so Uganda's), and an officer who is Country
// Director in Kenya alone: Kenya's Country Director sees no Ugandan
// application, is refused it by its id, and manages only the Kenyan
// lender's channel; Uganda's Country Director sees the application and
// only the Ugandan lender. The officers' memberships are put back after;
// the lender's Kenyan record and the loan rows are removed.
func TestTheCountryThroughLoans(t *testing.T) {
	ctx := context.Background()
	loanFixtures(t)
	_, officer, exec := twoKenyans(t, "gcln")
	exec(`INSERT INTO country_registry.country_role_assignment (id, membership_id, country_id, user_id, role_name, scope_type, granted_by, grant_reason)
SELECT gen_random_uuid(), m.id, m.country_id, m.user_id, 'CountryDirector', 'country', 'gcln', 'Country test'
FROM country_registry.country_membership m WHERE m.user_id = $1 AND m.granted_by = 'gcln'`, officer.user)
	exec(`INSERT INTO country_registry.partner_country (partner_id, country_id, effective_from, source, recorded_by)
SELECT $1, id, current_date, 'import', 'gcln' FROM country_registry.country WHERE code = 'KE'`, lenderB)
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM country_registry.partner_country WHERE partner_id = $1`, lenderB); err != nil {
			t.Error(err)
		}
	})

	if response := submit(t, applicationForm(lenderA, "Gcln Primary School", "0772 000 911", "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1")); response.StatusCode != http.StatusSeeOther {
		t.Fatalf("the application was not taken: %d", response.StatusCode)
	}
	var applicationID, ugandaCD string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id::text FROM school_loans.application WHERE school_name = 'Gcln Primary School'),
  (SELECT id FROM "user" WHERE email = 'cd@edify.org')`).Scan(&applicationID, &ugandaCD); err != nil {
		t.Fatal(err)
	}

	client := loansClient()
	as := func(user string) string { return token(t, user, "CountryDirector", time.Hour) }
	list := func(user string) []string {
		t.Helper()
		got, err := client.ListLoanApplications(ctx, authed(&loansv1.ListLoanApplicationsRequest{Page: 1}, as(user)))
		if err != nil {
			t.Fatalf("listing as %s: %v", user, err)
		}
		ids := []string{}
		for _, row := range got.Msg.GetRows() {
			ids = append(ids, row.GetId())
		}
		return ids
	}
	lenders := func(user string) []string {
		t.Helper()
		got, err := client.ListLenderChannels(ctx, authed(&loansv1.ListLenderChannelsRequest{}, as(user)))
		if err != nil {
			t.Fatalf("lender channels as %s: %v", user, err)
		}
		ids := []string{}
		for _, c := range got.Msg.GetChannels() {
			ids = append(ids, c.GetPartnerId())
		}
		return ids
	}

	if got := list(officer.user); slices.Contains(got, applicationID) {
		t.Error("Kenya's Country Director lists a Ugandan application")
	}
	if _, err := client.GetLoanApplication(ctx, authed(&loansv1.GetLoanApplicationRequest{Id: applicationID}, as(officer.user))); connect.CodeOf(err) != connect.CodeNotFound {
		t.Errorf("Kenya's Country Director opening a Ugandan application: %v", err)
	}
	if got := list(ugandaCD); !slices.Contains(got, applicationID) {
		t.Error("Uganda's Country Director does not list the Ugandan application")
	}
	if _, err := client.GetLoanApplication(ctx, authed(&loansv1.GetLoanApplicationRequest{Id: applicationID}, as(ugandaCD))); err != nil {
		t.Errorf("Uganda's Country Director opening it: %v", err)
	}
	if got := lenders(officer.user); !slices.Contains(got, lenderB) || slices.Contains(got, lenderA) {
		t.Errorf("Kenya's Country Director manages lenders %v, want the Kenyan one alone", got)
	}
	if got := lenders(ugandaCD); slices.Contains(got, lenderB) || !slices.Contains(got, lenderA) {
		t.Errorf("Uganda's Country Director manages lenders %v, want the Ugandan one and not Kenya's", got)
	}
	if _, err := client.SendChannelConfirmation(ctx, authed(&loansv1.SendChannelConfirmationRequest{PartnerId: lenderA}, as(officer.user))); connect.CodeOf(err) != connect.CodeNotFound {
		t.Errorf("Kenya's Country Director confirming a Ugandan lender's address: %v", err)
	}
}
