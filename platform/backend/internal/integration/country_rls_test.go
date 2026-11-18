//go:build integration

package integration

import (
	"context"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/countryctx"
)

// Country isolation in the database (docs/migration/80-multi-country-phase-0.md
// §23). Through a pool of one connection as the gateway's own role — so the
// same session serves every request in turn — a Ugandan application is read
// by a reader working in Uganda, by the Admin and by the platform's own
// work, and by nobody working in Kenya or in no country, however the
// requests alternate on the connection; a Kenyan reader cannot change it,
// nor file an application as Uganda's. The rows are removed after.
func TestTheDatabaseKeepsEachRequestToItsCountry(t *testing.T) {
	ctx := context.Background()
	loanFixtures(t)
	exec := func(sql string, args ...any) {
		t.Helper()
		if _, err := admin.Exec(ctx, sql, args...); err != nil {
			t.Fatalf("%s: %v", sql, err)
		}
	}
	// One Ugandan application, filed as the owner (who is not bound by the
	// policies' roles).
	exec(`INSERT INTO school_loans.application (id, reference, idempotency_key, receipt_token_hash, receipt_expires_at, source,
  school_name, director_name, director_phone, district_name, sub_county_name, parish_name, village_name, boys, girls,
  average_fees_collected_ugx, purpose_code, purpose_label, requested_amount_ugx, partner_id, lender_id, lender_name, consent_version,
  consent_recorded_at, school_match_status, status, delivery_status, submitted_at, updated_at, country_code)
SELECT gen_random_uuid(), 'GCRLS-1', repeat('d', 32), repeat('e', 64), now() + interval '1 day', 'public_link',
  'Gcrls School', 'Director', '+256772000999', 'Mukono', 'Goma', 'Seeta', 'Namilyango', 10, 10,
  1000000, 'school_furniture', 'School furniture', 2000000, $1, (SELECT loan_lender_id FROM partner WHERE id = $1), 'Integration Lender A', 'v1',
  now(), 'unmatched', 'submitted', 'queued', now(), now(), 'UG'`, lenderA)

	cfg := gateway.Config().Copy()
	cfg.MaxConns, cfg.MinConns = 1, 1
	countryctx.Configure(cfg)
	one, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer one.Close()

	in := func(code string) *country.Work {
		return &country.Work{Country: country.Country{ID: countryID(t, code), Code: code}, RolesSource: country.RolesFromProfile}
	}
	as := func(role string, w *country.Work) context.Context {
		return auth.WithPrincipal(ctx, auth.Principal{Account: auth.Account{UserID: "gcrls", ActiveRole: role, Country: w}})
	}
	readers := []struct {
		who  string
		ctx  context.Context
		sees bool
	}{
		{"a Country Director working in Uganda", as("CountryDirector", in("UG")), true},
		{"a Country Director working in Kenya", as("CountryDirector", in("KE")), false},
		{"the Admin", as("Admin", in("KE")), true},
		{"a CCEO working in no Active country", as("CCEO", nil), false},
		{"the platform's own work", ctx, true},
	}
	seen := func(c context.Context) bool {
		t.Helper()
		var n int
		if err := one.QueryRow(c, `SELECT count(*) FROM school_loans.application WHERE reference = 'GCRLS-1'`).Scan(&n); err != nil {
			t.Fatal(err)
		}
		return n == 1
	}
	// Twice over, so each request takes the connection the one before used.
	for round := 0; round < 2; round++ {
		for _, r := range readers {
			if got := seen(r.ctx); got != r.sees {
				t.Errorf("round %d, %s: sees the Ugandan application %v, want %v", round, r.who, got, r.sees)
			}
		}
	}

	// Writing: a Kenyan reader changes no Ugandan row and files none as Uganda's.
	kenyan := as("CountryDirector", in("KE"))
	err = pgx.BeginTxFunc(kenyan, one, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		tag, err := tx.Exec(kenyan, `UPDATE school_loans.application SET school_name = 'Changed' WHERE reference = 'GCRLS-1'`)
		if err != nil {
			return err
		}
		if tag.RowsAffected() != 0 {
			t.Errorf("a Kenyan reader changed %d Ugandan applications", tag.RowsAffected())
		}
		return nil
	})
	if err != nil {
		t.Fatalf("the Kenyan update: %v", err)
	}
	err = pgx.BeginTxFunc(kenyan, one, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		_, err := tx.Exec(kenyan, `INSERT INTO school_loans.application (id, reference, idempotency_key, receipt_token_hash,
  receipt_expires_at, source, school_name, director_name, director_phone, district_name, sub_county_name, parish_name,
  village_name, boys, girls, average_fees_collected_ugx, purpose_code, purpose_label, requested_amount_ugx, partner_id,
  lender_id, lender_name, consent_version, consent_recorded_at, school_match_status, status, delivery_status, submitted_at, updated_at, country_code)
SELECT gen_random_uuid(), 'GCRLS-2', repeat('f', 32), repeat('a', 64), now() + interval '1 day', 'public_link',
  'Gcrls Other', 'Director', '+256772000998', 'Mukono', 'Goma', 'Seeta', 'Namilyango', 10, 10,
  1000000, 'school_furniture', 'School furniture', 2000000, $1, (SELECT loan_lender_id FROM partner WHERE id = $1), 'Integration Lender A', 'v1',
  now(), 'unmatched', 'submitted', 'queued', now(), now(), 'UG'`, lenderA)
		return err
	})
	if !refusedByRowSecurity(err) {
		t.Errorf("a Kenyan reader filing a Ugandan application: %v", err)
	}
}
