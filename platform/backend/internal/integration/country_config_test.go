//go:build integration

package integration

import (
	"context"
	"errors"
	"net/http"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1/countriesv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// insufficientPrivilege is what row-level security answers a refused write.
const insufficientPrivilege = "42501"

// inGatewayTx runs work as the gateway's own role in a transaction that is
// always rolled back, and returns work's error.
func inGatewayTx(t *testing.T, work func(ctx context.Context, tx pgx.Tx) error) error {
	t.Helper()
	ctx := context.Background()
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	return work(ctx, tx)
}

func countryID(t *testing.T, code string) string {
	t.Helper()
	var id string
	if err := admin.QueryRow(context.Background(), `SELECT id::text FROM country_registry.country WHERE code = $1`, code).Scan(&id); err != nil {
		t.Fatal(err)
	}
	return id
}

func refusedByRowSecurity(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == insufficientPrivilege
}

// The registry's row-level security (country/schema 0002), as the gateway's
// role meets it: every row is readable, and a write lands only for the
// countries its transaction declares.
func TestTheRegistryRefusesUndeclaredWrites(t *testing.T) {
	kenya, uganda := countryID(t, "KE"), countryID(t, "UG")
	addSettings := func(ctx context.Context, tx pgx.Tx, id string) error {
		_, err := tx.Exec(ctx, `INSERT INTO country_registry.country_config_version
  (id, country_id, version, default_language, languages, currency_code, currency_minor_units, time_zone,
   date_format, fy_start_month, effective_from, changed_by, change_reason)
VALUES (gen_random_uuid(), $1::uuid, 99, 'en', '{en}', 'KES', 0, 'Africa/Nairobi', 'j M Y', 7, current_date, 'gcty', 'rls test')`, id)
		return err
	}

	if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error {
		var n int
		if err := tx.QueryRow(ctx, `SELECT (SELECT count(*) FROM country_registry.country)
  + (SELECT count(*) FROM country_registry.school_country WHERE country_id = $1::uuid)`, uganda).Scan(&n); err != nil {
			return err
		}
		if n < 5 {
			t.Errorf("the gateway reads %d countries and Ugandan schools", n)
		}
		return nil
	}); err != nil {
		t.Fatalf("reading: %v", err)
	}

	if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error { return addSettings(ctx, tx, kenya) }); !refusedByRowSecurity(err) {
		t.Errorf("a write that declares no country: %v", err)
	}
	if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error {
		if err := country.WriteFor(ctx, tx, false, kenya); err != nil {
			return err
		}
		return addSettings(ctx, tx, kenya)
	}); err != nil {
		t.Errorf("Kenya's settings, declared for Kenya: %v", err)
	}
	if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error {
		if err := country.WriteFor(ctx, tx, false, kenya); err != nil {
			return err
		}
		return addSettings(ctx, tx, uganda)
	}); !refusedByRowSecurity(err) {
		t.Errorf("Uganda's settings, declared for Kenya: %v", err)
	}
	if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error {
		if err := country.WriteFor(ctx, tx, false, kenya); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `INSERT INTO country_registry.school_country (school_id, country_id, effective_from, source, recorded_by)
SELECT id, $1::uuid, current_date + 1, 'assignment', 'gcty' FROM school ORDER BY id LIMIT 1`, uganda)
		return err
	}); !refusedByRowSecurity(err) {
		t.Errorf("a school placed in Uganda, declared for Kenya: %v", err)
	}

	// A change the policy does not allow touches no row rather than failing.
	changed := func(platform bool, sql string, args ...any) int64 {
		t.Helper()
		var n int64
		if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error {
			if err := country.WriteFor(ctx, tx, platform, kenya); err != nil {
				return err
			}
			tag, err := tx.Exec(ctx, sql, args...)
			n = tag.RowsAffected()
			return err
		}); err != nil {
			t.Fatalf("%s: %v", sql, err)
		}
		return n
	}
	rename := `UPDATE country_registry.country SET name = name WHERE code = 'UG'`
	if n := changed(false, rename); n != 0 {
		t.Errorf("a country changed by a session that is not a platform one: %d rows", n)
	}
	if n := changed(true, rename); n != 1 {
		t.Errorf("a country changed by a platform session: %d rows", n)
	}
	revoke := `UPDATE country_registry.country_membership SET revoked_at = now(), revoked_by = 'gcty' WHERE country_id = $1::uuid`
	if n := changed(false, revoke, uganda); n != 0 {
		t.Errorf("Uganda's memberships revoked by a session declared for Kenya: %d rows", n)
	}

	// The legacy seed declares what it writes, so it runs as a role the
	// policies bind (it adds nothing to a seeded database).
	if err := inGatewayTx(t, func(ctx context.Context, tx pgx.Tx) error {
		seeded, err := country.SeedLegacy(ctx, tx, "gcty")
		if err == nil && seeded != (country.Seeded{}) {
			t.Errorf("a second seed added %+v", seeded)
		}
		return err
	}); err != nil {
		t.Errorf("the seed, as the gateway's role: %v", err)
	}
}

func countriesClient() countriesv1connect.CountryServiceClient {
	return countriesv1connect.NewCountryServiceClient(http.DefaultClient, baseURL)
}

// CountryService: who sees which countries, who records settings and for
// which, and how versions follow one another. Uganda's settings are never
// changed; Kenya's versions are removed after.
func TestCountrySettings(t *testing.T) {
	ctx := context.Background()
	kenya := countryID(t, "KE")
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM country_registry.country_config_version WHERE country_id = $1::uuid`, kenya); err != nil {
			t.Error(err)
		}
	}
	clear()
	t.Cleanup(clear)

	var adminID, cdID, cceoID, today, later string
	if err := admin.QueryRow(ctx, `SELECT
  (SELECT id FROM "user" WHERE email = 'admin@edify.org'), (SELECT id FROM "user" WHERE email = 'cd@edify.org'),
  (SELECT u.id FROM "user" u WHERE u.active_role = 'CCEO' AND u.deleted_at IS NULL ORDER BY u.id LIMIT 1),
  current_date::text, (current_date + 30)::text`).Scan(&adminID, &cdID, &cceoID, &today, &later); err != nil {
		t.Fatal(err)
	}
	asAdmin, asCD, asCCEO := token(t, adminID, "Admin", time.Hour), token(t, cdID, "CountryDirector", time.Hour),
		token(t, cceoID, "CCEO", time.Hour)
	client := countriesClient()
	codes := func(bearer string) []string {
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
	if got := codes(asAdmin); len(got) != 4 {
		t.Errorf("the Admin sees %v, want all four countries", got)
	}
	for name, bearer := range map[string]string{"the Country Director": asCD, "an officer": asCCEO} {
		if got := codes(bearer); len(got) != 1 || got[0] != "UG" {
			t.Errorf("%s sees %v, want Uganda alone", name, got)
		}
	}
	_, err := client.ListCountries(ctx, authed(&countriesv1.ListCountriesRequest{}, ""))
	requireCode(t, err, connect.CodeUnauthenticated, "")

	uganda, err := client.GetCountryConfig(ctx, authed(&countriesv1.GetCountryConfigRequest{CountryCode: "UG"}, asCD))
	if err != nil {
		t.Fatal(err)
	}
	if c := uganda.Msg.GetCountry().GetConfig(); c.GetCurrencyCode() != "UGX" || c.GetTimeZone() != "Africa/Kampala" ||
		c.GetFyStartMonth() != 10 || len(uganda.Msg.GetVersions()) != 1 {
		t.Errorf("Uganda's settings %+v, %d versions", c, len(uganda.Msg.GetVersions()))
	}
	_, err = client.GetCountryConfig(ctx, authed(&countriesv1.GetCountryConfigRequest{CountryCode: "KE"}, asCD))
	requireCode(t, err, connect.CodeNotFound, "")

	pilot := func(from string) *countriesv1.RecordCountryConfigRequest {
		return &countriesv1.RecordCountryConfigRequest{
			CountryCode: "KE", DefaultLanguage: "en", Languages: []string{"en", "sw"}, CurrencyCode: "KES",
			TimeZone: "Africa/Nairobi", DateFormat: "j M Y", Calendars: []string{"gregorian"}, FyStartMonth: 7,
			EffectiveFrom: from, ChangeReason: "Kenya pilot settings",
		}
	}
	record := func(bearer string, r *countriesv1.RecordCountryConfigRequest) (*countriesv1.RecordCountryConfigResponse, error) {
		got, err := client.RecordCountryConfig(ctx, authed(r, bearer))
		if err != nil {
			return nil, err
		}
		return got.Msg, nil
	}
	_, err = record(asCD, pilot(""))
	requireCode(t, err, connect.CodePermissionDenied, "")
	ugandaChange := pilot("")
	ugandaChange.CountryCode = "UG"
	_, err = record(asAdmin, ugandaChange)
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	badZone := pilot("")
	badZone.TimeZone = "Africa/Atlantis"
	_, err = record(asAdmin, badZone)
	requireCode(t, err, connect.CodeInvalidArgument, "")
	_, err = record(asAdmin, pilot("2020-01-01"))
	requireCode(t, err, connect.CodeFailedPrecondition, "")

	first, err := record(asAdmin, pilot(""))
	if err != nil {
		t.Fatal(err)
	}
	if r := first.GetRecorded(); r.GetVersion() != 1 || r.GetEffectiveFrom() != today || r.GetChangedBy() != adminID ||
		first.GetCountry().GetConfig().GetVersion() != 1 {
		t.Errorf("first version %+v, in force %+v", r, first.GetCountry().GetConfig())
	}
	_, err = record(asAdmin, pilot(today))
	requireCode(t, err, connect.CodeFailedPrecondition, "")
	second, err := record(asAdmin, pilot(later))
	if err != nil {
		t.Fatal(err)
	}
	if second.GetRecorded().GetVersion() != 2 || second.GetCountry().GetConfig().GetVersion() != 1 {
		t.Errorf("a later version %d, in force %d", second.GetRecorded().GetVersion(), second.GetCountry().GetConfig().GetVersion())
	}
	history, err := client.GetCountryConfig(ctx, authed(&countriesv1.GetCountryConfigRequest{CountryCode: "KE"}, asAdmin))
	if err != nil {
		t.Fatal(err)
	}
	if v := history.Msg.GetVersions(); len(v) != 2 || v[0].GetVersion() != 2 || v[1].GetEffectiveUntil() != later {
		t.Errorf("Kenya's versions %+v", v)
	}

	// Uganda's settings are as the seed left them.
	var ugandan int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM country_registry.country_config_version v
JOIN country_registry.country c ON c.id = v.country_id WHERE c.code = 'UG' AND v.effective_until IS NULL`).Scan(&ugandan); err != nil {
		t.Fatal(err)
	}
	if ugandan != 1 {
		t.Errorf("Uganda has %d open settings versions", ugandan)
	}
}
