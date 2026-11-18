package country

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// The geographic registry (migration 0007, docs/migration/80 §25): each
// country's levels of administrative units and its units, Uganda's mapped
// in from the existing tables by id.

// existingLevel is one of the existing application's geography tables, the
// level it is in Uganda, and the existing columns that name its parent, in
// the order they are tried (a district under its sub-region, else its
// region; a sub-county under its county, else its district).
type existingLevel struct {
	table, label string
	level        int
	required     bool
	// code is the SQL for the unit's official code, over the row e.
	code string
	// verified is the SQL saying the existing row's source recorded it as
	// official, over the row e.
	verified string
	parents  []existingParent
}

type existingParent struct{ table, column string }

// ExistingLevels are Uganda's levels as the existing application keeps
// them (docs/migration/80 §1: region → sub-region → district → county →
// sub-county → parish → village). A cluster must have a district there, as
// the existing tables require, and a district its region; the others are
// optional.
var ExistingLevels = []existingLevel{
	{table: "region", label: "Region", level: 1, required: true,
		code: officialCode, verified: `false`},
	{table: "sub_region", label: "Sub-region", level: 2,
		code: `NULL::text`, verified: `(e.confidence = 'VERIFIED')`,
		parents: []existingParent{{"region", "region_id"}}},
	{table: "district", label: "District", level: 3, required: true,
		code: officialCode, verified: ubos,
		parents: []existingParent{{"sub_region", "sub_region_id"}, {"region", "region_id"}}},
	{table: "county", label: "County", level: 4,
		code: pcode, verified: ubos,
		parents: []existingParent{{"district", "district_id"}}},
	{table: "sub_county", label: "Sub-county", level: 5,
		code: pcode, verified: ubos,
		parents: []existingParent{{"county", "county_id"}, {"district", "district_id"}}},
	{table: "parish", label: "Parish", level: 6,
		code: pcode, verified: `false`,
		parents: []existingParent{{"sub_county", "sub_county_id"}}},
	{table: "village", label: "Village", level: 7,
		code: `NULL::text`, verified: `false`,
		parents: []existingParent{{"parish", "parish_id"}}},
}

const (
	pcode        = `NULLIF(btrim(e.pcode), '')`
	officialCode = `COALESCE(NULLIF(btrim(e.pcode), ''), NULLIF(btrim(e.code), ''))`
	ubos         = `(COALESCE(e.source, '') LIKE 'UBOS%')`
	// heldID is the holding country's id: the one whose roles are the
	// existing profile's (Uganda).
	heldID = `(SELECT hc.id FROM country_registry.country hc WHERE hc.roles_source = '` + RolesFromProfile + `' ORDER BY hc.code LIMIT 1)`
)

// SeededGeography is what one SeedGeography run added.
type SeededGeography struct{ Types, Units int64 }

// SeedGeography registers Uganda's levels and maps every existing unit in
// by id: under its parent's country, a region under the country its
// existing row names (country_alias), and a unit with no parent under the
// holding country's. A unit whose region names a country with no levels
// yet, whose parent is not mapped, or whose name is blank is left out, and
// Reconcile reports it. It writes only country_registry's tables and reads
// only the existing geography; run again, it adds only what is missing. by
// is who ran it.
func SeedGeography(ctx context.Context, tx pgx.Tx, by string) (SeededGeography, error) {
	var out SeededGeography
	if _, err := tx.Exec(ctx, `SELECT set_config('edify.write_countries', string_agg(id::text, ','), true)
FROM country_registry.country`); err != nil {
		return out, fmt.Errorf("country: declaring the geography seeded: %w", err)
	}
	for _, l := range ExistingLevels {
		tag, err := tx.Exec(ctx, `INSERT INTO country_registry.admin_unit_type
  (id, country_id, canonical_type, local_label, level, is_required, effective_from, created_by)
SELECT gen_random_uuid(), `+heldID+`, $1, $2, $3, $4, $5::date, $6
WHERE `+heldID+` IS NOT NULL AND NOT EXISTS (SELECT 1 FROM country_registry.admin_unit_type t
  WHERE t.country_id = `+heldID+` AND t.canonical_type = $1 AND t.effective_to IS NULL)`,
			l.table, l.label, l.level, l.required, LegacySince, by)
		if err != nil {
			return out, fmt.Errorf("country: seeding the %s level: %w", l.table, err)
		}
		out.Types += tag.RowsAffected()
	}
	for _, l := range ExistingLevels {
		tag, err := tx.Exec(ctx, mapLevelSQL(l), LegacySince, by)
		if err != nil {
			return out, fmt.Errorf("country: mapping the existing %s rows: %w", l.table, err)
		}
		out.Units += tag.RowsAffected()
	}
	return out, nil
}

// parentSQL is the SQL for the mapped unit that is the existing row e's
// parent, trying the level's parent columns in order; "" for a top level.
func parentSQL(l existingLevel, alias string) string {
	if len(l.parents) == 0 {
		return ""
	}
	sql := `COALESCE(`
	for i, p := range l.parents {
		if i > 0 {
			sql += `, `
		}
		sql += fmt.Sprintf(`(SELECT %[1]s.id FROM country_registry.admin_unit %[1]s WHERE %[1]s.existing_table = '%[2]s' AND %[1]s.existing_id = e.%[3]s)`,
			alias, p.table, p.column)
	}
	return sql + `)`
}

// mapLevelSQL maps the level's existing rows not yet mapped; $1 is the day
// they are valid from, $2 who ran it.
func mapLevelSQL(l existingLevel) string {
	parent, wantsParent := `NULL::uuid`, `false`
	if len(l.parents) > 0 {
		parent, wantsParent = parentSQL(l, "pu"), `(`
		for i, p := range l.parents {
			if i > 0 {
				wantsParent += ` OR `
			}
			wantsParent += fmt.Sprintf(`e.%s IS NOT NULL`, p.column)
		}
		wantsParent += `)`
	}
	// A region's country is the one its existing row names; a unit with no
	// parent at all, the holding country.
	root := heldID
	if l.table == "region" {
		root = `COALESCE((SELECT a.country_id FROM country_registry.country_alias a WHERE a.alias = btrim(e.country)), ` + heldID + `)`
	}
	return fmt.Sprintf(`WITH src AS (
  SELECT e.id, btrim(e.name) AS name, %[2]s AS code, %[3]s AS verified, %[4]s AS parent_id, %[5]s AS wants_parent,
    %[6]s AS root_country
  FROM %[1]s e
  WHERE btrim(COALESCE(e.name, '')) <> ''
    AND NOT EXISTS (SELECT 1 FROM country_registry.admin_unit m WHERE m.existing_table = '%[1]s' AND m.existing_id = e.id)
), placed AS (
  SELECT src.*, COALESCE(p.country_id, src.root_country) AS country_id, p.id AS mapped_parent,
    count(*) OVER (PARTITION BY src.code) AS same_code
  FROM src LEFT JOIN country_registry.admin_unit p ON p.id = src.parent_id
  WHERE NOT src.wants_parent OR p.id IS NOT NULL
)
INSERT INTO country_registry.admin_unit
  (id, country_id, type_id, official_name, official_code, parent_id, valid_from, source, verification_status,
   existing_table, existing_id, created_by)
SELECT gen_random_uuid(), placed.country_id, t.id, placed.name, CASE WHEN placed.same_code = 1 THEN placed.code END,
  placed.mapped_parent, $1::date, 'existing_table', CASE WHEN placed.verified THEN 'verified' ELSE 'unverified' END,
  '%[1]s', placed.id, $2
FROM placed JOIN country_registry.admin_unit_type t
  ON t.country_id = placed.country_id AND t.canonical_type = '%[1]s' AND t.effective_to IS NULL
ON CONFLICT DO NOTHING`, l.table, l.code, l.verified, parent, wantsParent, root)
}

// LevelReconciliation is how one existing geography table stands against
// the registry.
type LevelReconciliation struct {
	Table string
	// Existing is the existing table's rows; Mapped those the registry
	// maps; Unmapped the ids of the rows it does not (at most ten).
	Existing, Mapped int64
	Unmapped         []string
	// Renamed is mapped units whose name no longer matches the existing
	// row's; Moved those whose parent no longer does.
	Renamed, Moved int64
}

// Reconciled says whether every existing row is mapped, under its own name
// and parent.
func (r LevelReconciliation) Reconciled() bool {
	return r.Existing == r.Mapped && r.Renamed == 0 && r.Moved == 0
}

// Reconcile compares every existing geography table with the registry one
// to one (docs/migration/80 §8: "Uganda's school counts, IDs and locations
// reconcile one to one"). It only reads.
func Reconcile(ctx context.Context, q Querier) ([]LevelReconciliation, error) {
	out := make([]LevelReconciliation, 0, len(ExistingLevels))
	for _, l := range ExistingLevels {
		r := LevelReconciliation{Table: l.table}
		moved := `0::bigint`
		if len(l.parents) > 0 {
			moved = `count(*) FILTER (WHERE u.id IS NOT NULL AND u.parent_id IS DISTINCT FROM ` + parentSQL(l, "cp") + `)`
		}
		err := q.QueryRow(ctx, fmt.Sprintf(`SELECT count(*), count(u.id),
  count(*) FILTER (WHERE u.id IS NOT NULL AND u.official_name <> btrim(e.name)), %[2]s,
  COALESCE((array_agg(e.id::text ORDER BY e.id) FILTER (WHERE u.id IS NULL))[1:10], '{}')
FROM %[1]s e LEFT JOIN country_registry.admin_unit u ON u.existing_table = '%[1]s' AND u.existing_id = e.id`, l.table, moved)).
			Scan(&r.Existing, &r.Mapped, &r.Renamed, &r.Moved, &r.Unmapped)
		if err != nil {
			return nil, fmt.Errorf("country: reconciling the %s rows: %w", l.table, err)
		}
		out = append(out, r)
	}
	return out, nil
}
