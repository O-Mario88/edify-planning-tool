//go:build integration

package integration

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5/pgconn"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// The geographic registry (docs/migration/80-multi-country-phase-0.md §25):
// seeding maps every existing geography row in by id, one to one, under its
// own name and parent and in Uganda; run again it adds nothing; and the
// database keeps a country's units to writes declared for that country and
// a unit's parent to its own country. Everything is rolled back.
func TestTheGeographyRegistryMapsUgandaOneToOne(t *testing.T) {
	ctx := context.Background()
	tx, err := admin.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	// The rows other tests added since the seed are mapped first, so the
	// second run below must add nothing.
	if _, err := country.SeedGeography(ctx, tx, "gcgeo"); err != nil {
		t.Fatal(err)
	}
	again, err := country.SeedGeography(ctx, tx, "gcgeo")
	if err != nil {
		t.Fatal(err)
	}
	if again.Types != 0 || again.Units != 0 {
		t.Errorf("a second seed added %d levels and %d units, want none", again.Types, again.Units)
	}
	levels, err := country.Reconcile(ctx, tx)
	if err != nil {
		t.Fatal(err)
	}
	if len(levels) != len(country.ExistingLevels) {
		t.Fatalf("reconciled %d tables, want %d", len(levels), len(country.ExistingLevels))
	}
	for _, l := range levels {
		if !l.Reconciled() {
			t.Errorf("%s: %d existing, %d mapped, %d renamed, %d moved, unmapped %v",
				l.Table, l.Existing, l.Mapped, l.Renamed, l.Moved, l.Unmapped)
		}
	}
	// Every mapped unit is Uganda's, at its own table's level.
	var elsewhere, wrongLevel int
	if err := tx.QueryRow(ctx, `SELECT count(*) FILTER (WHERE c.code <> 'UG'), count(*) FILTER (WHERE t.canonical_type <> u.existing_table)
FROM country_registry.admin_unit u JOIN country_registry.country c ON c.id = u.country_id
JOIN country_registry.admin_unit_type t ON t.id = u.type_id WHERE u.existing_table IS NOT NULL`).Scan(&elsewhere, &wrongLevel); err != nil {
		t.Fatal(err)
	}
	if elsewhere != 0 || wrongLevel != 0 {
		t.Errorf("%d mapped units outside Uganda and %d at another level, want none", elsewhere, wrongLevel)
	}

	// The database's own guard, as the gateway's role meets it.
	var ug, ke string
	if err := tx.QueryRow(ctx, `SELECT (SELECT id::text FROM country_registry.country WHERE code = 'UG'),
  (SELECT id::text FROM country_registry.country WHERE code = 'KE')`).Scan(&ug, &ke); err != nil {
		t.Fatal(err)
	}
	if _, err := tx.Exec(ctx, `SET LOCAL ROLE edify_gateway`); err != nil {
		t.Fatal(err)
	}
	attempt := func(writeFor, sql string, args ...any) (int64, error) {
		t.Helper()
		if _, err := tx.Exec(ctx, `SAVEPOINT attempt`); err != nil {
			t.Fatal(err)
		}
		if _, err := tx.Exec(ctx, `SELECT set_config('edify.write_countries', $1, true)`, writeFor); err != nil {
			t.Fatal(err)
		}
		tag, err := tx.Exec(ctx, sql, args...)
		if _, rollbackErr := tx.Exec(ctx, `ROLLBACK TO SAVEPOINT attempt`); rollbackErr != nil {
			t.Fatal(rollbackErr)
		}
		return tag.RowsAffected(), err
	}
	addUgandanParish := `INSERT INTO country_registry.admin_unit (id, country_id, type_id, official_name, valid_from, source,
  verification_status, created_by)
SELECT gen_random_uuid(), $1::uuid, t.id, 'Gcgeo Parish', current_date, 'manual', 'unverified', 'gcgeo'
FROM country_registry.admin_unit_type t WHERE t.country_id = $1::uuid AND t.canonical_type = 'parish'`
	if n, err := attempt(ug, addUgandanParish, ug); err != nil || n != 1 {
		t.Errorf("a write declared for Uganda adding a Ugandan unit: %d added, %v", n, err)
	}
	if _, err := attempt(ke, addUgandanParish, ug); !refusedByRowSecurity(err) {
		t.Errorf("a write declared for Kenya adding a Ugandan unit: %v", err)
	}
	if n, err := attempt(ke, `UPDATE country_registry.admin_unit SET official_name = 'Changed' WHERE country_id = $1::uuid`, ug); err != nil || n != 0 {
		t.Errorf("a write declared for Kenya changing Ugandan units: %d changed, %v", n, err)
	}
	// A Kenyan level, and a Kenyan unit under a Ugandan parent, which the
	// composite key refuses.
	if _, err := attempt(ke+","+ug, `WITH kt AS (
  INSERT INTO country_registry.admin_unit_type (id, country_id, canonical_type, local_label, level, effective_from, created_by)
  VALUES (gen_random_uuid(), $1::uuid, 'county', 'County', 1, current_date, 'gcgeo') RETURNING id)
INSERT INTO country_registry.admin_unit (id, country_id, type_id, official_name, parent_id, valid_from, source,
  verification_status, created_by)
SELECT gen_random_uuid(), $1::uuid, kt.id, 'Gcgeo County', (SELECT u.id FROM country_registry.admin_unit u
  WHERE u.country_id = $2::uuid AND u.existing_table = 'region' ORDER BY u.existing_id LIMIT 1), current_date, 'manual',
  'unverified', 'gcgeo'
FROM kt`, ke, ug); !foreignKeyRefused(err) {
		t.Errorf("a Kenyan unit under a Ugandan parent: %v", err)
	}
}

func foreignKeyRefused(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23503"
}

// The registry through the gateway (docs/migration/80 §26): a Country
// Director working in Uganda reads Uganda's levels and drills down its
// units with each one's chain, and cannot see Kenya's or define a level; an
// Admin defines Kenya's levels and adds its units under parents of a higher
// level in Kenya, and changes none of Uganda's. Kenya's levels and units
// are removed after.
func TestTheGeographyRegistryThroughTheGateway(t *testing.T) {
	ctx := context.Background()
	var adminID, cdID, keID string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM "user" WHERE email = 'admin@edify.org'),
  (SELECT id FROM "user" WHERE email = 'cd@edify.org'), (SELECT id::text FROM country_registry.country WHERE code = 'KE')`).
		Scan(&adminID, &cdID, &keID); err != nil {
		t.Fatal(err)
	}
	clear := func() {
		for _, sql := range []string{
			`DELETE FROM country_registry.admin_unit WHERE country_id = $1::uuid AND created_by = $2`,
			`DELETE FROM country_registry.admin_unit_type WHERE country_id = $1::uuid AND created_by = $2`,
		} {
			if _, err := admin.Exec(ctx, sql, keID, adminID); err != nil {
				t.Fatalf("%s: %v", sql, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	asAdmin, asCD := token(t, adminID, "Admin", time.Hour), token(t, cdID, "CountryDirector", time.Hour)
	client := countriesClient()
	codeOf := func(err error) connect.Code { return connect.CodeOf(err) }

	// Uganda, read by its Country Director.
	levels, err := client.ListAdminUnitLevels(ctx, authed(&countriesv1.ListAdminUnitLevelsRequest{CountryCode: "UG"}, asCD))
	if err != nil {
		t.Fatal(err)
	}
	var districts int64
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM district`).Scan(&districts); err != nil {
		t.Fatal(err)
	}
	words := []string{}
	for _, l := range levels.Msg.GetLevels() {
		words = append(words, l.GetCanonicalType())
		if l.GetCanonicalType() == "district" && l.GetUnitCount() != districts {
			t.Errorf("Uganda's districts: %d, want the %d existing", l.GetUnitCount(), districts)
		}
	}
	if got := strings.Join(words, ","); got != "region,sub_region,district,county,sub_county,parish,village" {
		t.Errorf("Uganda's levels: %s", got)
	}
	top, err := client.ListAdminUnits(ctx, authed(&countriesv1.ListAdminUnitsRequest{CountryCode: "UG"}, asCD))
	if err != nil {
		t.Fatal(err)
	}
	var regions int64
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM region`).Scan(&regions); err != nil {
		t.Fatal(err)
	}
	if top.Msg.GetTotal() < regions || len(top.Msg.GetTrail()) != 0 {
		t.Fatalf("Uganda's top: %d units and a trail of %d, want at least the %d regions and none", top.Msg.GetTotal(),
			len(top.Msg.GetTrail()), regions)
	}
	var region *countriesv1.AdminUnit
	for _, u := range top.Msg.GetUnits() {
		if u.GetLevelLabel() == "Region" && u.GetChildCount() > 0 {
			region = u
			break
		}
	}
	if region == nil {
		t.Fatal("no Ugandan region with units under it")
	}
	under, err := client.ListAdminUnits(ctx, authed(&countriesv1.ListAdminUnitsRequest{CountryCode: "UG", ParentId: region.GetId()}, asCD))
	if err != nil {
		t.Fatal(err)
	}
	if under.Msg.GetTotal() != region.GetChildCount() || len(under.Msg.GetTrail()) != 1 || under.Msg.GetTrail()[0].GetId() != region.GetId() {
		t.Errorf("under %s: %d units (want %d), trail %v", region.GetOfficialName(), under.Msg.GetTotal(), region.GetChildCount(), under.Msg.GetTrail())
	}
	for _, u := range under.Msg.GetUnits() {
		if u.GetParentId() != region.GetId() || u.GetSource() != "existing_table" {
			t.Errorf("a unit under %s: %+v", region.GetOfficialName(), u)
		}
	}
	if _, err := client.ListAdminUnitLevels(ctx, authed(&countriesv1.ListAdminUnitLevelsRequest{CountryCode: "KE"}, asCD)); codeOf(err) != connect.CodeNotFound {
		t.Errorf("a Ugandan Country Director reading Kenya's levels: %v", err)
	}
	if _, err := client.DefineAdminUnitLevel(ctx, authed(&countriesv1.DefineAdminUnitLevelRequest{CountryCode: "KE",
		CanonicalType: "county", LocalLabel: "County", Level: 1}, asCD)); codeOf(err) != connect.CodePermissionDenied {
		t.Errorf("a Country Director defining a level: %v", err)
	}
	if _, err := client.DefineAdminUnitLevel(ctx, authed(&countriesv1.DefineAdminUnitLevelRequest{CountryCode: "UG",
		CanonicalType: "zone", LocalLabel: "Zone", Level: 8}, asAdmin)); codeOf(err) != connect.CodeFailedPrecondition {
		t.Errorf("an Admin defining a level for Active Uganda: %v", err)
	}

	// Kenya, set up by an Admin.
	define := func(word, label string, level int32) (*countriesv1.AdminUnitLevel, error) {
		got, err := client.DefineAdminUnitLevel(ctx, authed(&countriesv1.DefineAdminUnitLevelRequest{CountryCode: "KE",
			CanonicalType: word, LocalLabel: label, Level: level, IsRequired: level == 1}, asAdmin))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetLevel(), nil
	}
	county, err := define("county", "County", 1)
	if err != nil {
		t.Fatal(err)
	}
	subCounty, err := define("sub_county", "Sub-county", 2)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := define("ward", "Ward", 2); codeOf(err) != connect.CodeFailedPrecondition {
		t.Errorf("a second live level 2: %v", err)
	}
	add := func(level, parent, name, code string) (*countriesv1.AdminUnit, error) {
		got, err := client.AddAdminUnit(ctx, authed(&countriesv1.AddAdminUnitRequest{CountryCode: "KE", LevelId: level,
			ParentId: parent, OfficialName: name, OfficialCode: code}, asAdmin))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetUnit(), nil
	}
	nairobi, err := add(county.GetId(), "", "Nairobi", "047")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := add(county.GetId(), "", "Another Nairobi", "047"); codeOf(err) != connect.CodeFailedPrecondition {
		t.Errorf("a second county with code 047: %v", err)
	}
	if _, err := add(subCounty.GetId(), "", "Westlands", ""); codeOf(err) != connect.CodeFailedPrecondition {
		t.Errorf("a sub-county with no parent: %v", err)
	}
	westlands, err := add(subCounty.GetId(), nairobi.GetId(), "Westlands", "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := add(county.GetId(), westlands.GetId(), "Below", ""); codeOf(err) != connect.CodeFailedPrecondition {
		t.Errorf("a county under a sub-county: %v", err)
	}
	if _, err := add(subCounty.GetId(), region.GetId(), "Over the border", ""); codeOf(err) != connect.CodeFailedPrecondition {
		t.Errorf("a Kenyan sub-county under a Ugandan region: %v", err)
	}
	inNairobi, err := client.ListAdminUnits(ctx, authed(&countriesv1.ListAdminUnitsRequest{CountryCode: "KE", ParentId: nairobi.GetId()}, asAdmin))
	if err != nil {
		t.Fatal(err)
	}
	if inNairobi.Msg.GetTotal() != 1 || inNairobi.Msg.GetUnits()[0].GetId() != westlands.GetId() ||
		len(inNairobi.Msg.GetTrail()) != 1 || inNairobi.Msg.GetTrail()[0].GetChildCount() != 1 {
		t.Errorf("in Nairobi: %+v", inNairobi.Msg)
	}
	if _, err := client.ListAdminUnits(ctx, authed(&countriesv1.ListAdminUnitsRequest{CountryCode: "UG", ParentId: nairobi.GetId()}, asAdmin)); codeOf(err) != connect.CodeNotFound {
		t.Errorf("Nairobi read as Uganda's: %v", err)
	}
}
