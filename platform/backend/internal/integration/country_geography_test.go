//go:build integration

package integration

import (
	"context"
	"errors"
	"testing"

	"github.com/jackc/pgx/v5/pgconn"

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
