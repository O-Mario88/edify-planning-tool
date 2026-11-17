package country

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// LegacySince is when Uganda's settings take effect in the registry: before
// any record the platform holds, so every historical period reads them.
const LegacySince = "2000-10-01"

// registered are the countries Phase 1 registers (owner, 2026-11-17: codes
// UG, KE, RW, ET). Only Uganda is Active; the others are Draft until their
// settings are approved and they are validated (docs/migration/80, §7).
var registered = []struct{ code, name, state string }{
	{"UG", "Uganda", StateActive},
	{"KE", "Kenya", StateDraft},
	{"RW", "Rwanda", StateDraft},
	{"ET", "Ethiopia", StateDraft},
}

// Seeded is what one SeedLegacy run added.
type Seeded struct {
	Countries, Settings, Aliases, Schools, Memberships int64
}

// SeedLegacy registers the countries and maps the existing application's
// records to Uganda (owner, 2026-11-17: "every existing record is Uganda's,
// mapped to UG without rewriting it"): Uganda's settings as the platform
// runs today, the names the existing tables give each country, every
// existing school and every existing account. It writes only
// country_registry's tables and reads only the existing school and account
// ids; run again, it adds only what is missing. by is who ran it.
func SeedLegacy(ctx context.Context, tx pgx.Tx, by string) (Seeded, error) {
	var out Seeded
	exec := func(what string, n *int64, sql string, args ...any) error {
		tag, err := tx.Exec(ctx, sql, args...)
		if err != nil {
			return fmt.Errorf("country: seeding %s: %w", what, err)
		}
		*n += tag.RowsAffected()
		return nil
	}
	for _, c := range registered {
		if err := exec("the countries", &out.Countries, `INSERT INTO country_registry.country
  (id, code, name, state, activated_on, created_by, updated_by)
VALUES (gen_random_uuid(), $1, $2, $3, CASE WHEN $3 = 'active' THEN current_date END, $4, $4)
ON CONFLICT (code) DO NOTHING`, c.code, c.name, c.state, by); err != nil {
			return out, err
		}
		for _, alias := range []string{c.code, c.name} {
			if err := exec("the names", &out.Aliases, `INSERT INTO country_registry.country_alias (alias, country_id, created_by)
SELECT $1, id, $3 FROM country_registry.country WHERE code = $2
ON CONFLICT (alias) DO NOTHING`, alias, c.code, by); err != nil {
				return out, err
			}
		}
	}
	// Uganda as the platform runs today: English, whole shillings, East
	// African time, financial years from October.
	if err := exec("Uganda's settings", &out.Settings, `INSERT INTO country_registry.country_config_version
  (id, country_id, version, default_language, languages, currency_code, currency_minor_units, time_zone,
   date_format, calendars, fy_start_month, effective_from, changed_by, change_reason)
SELECT gen_random_uuid(), id, 1, 'en', '{en}', 'UGX', 0, 'Africa/Kampala', 'j M Y', '{gregorian}', 10, $2::date, $1,
  'Uganda as the platform ran before Edify Global'
FROM country_registry.country WHERE code = 'UG'
ON CONFLICT (country_id, version) DO NOTHING`, by, LegacySince); err != nil {
		return out, err
	}
	if err := exec("the schools", &out.Schools, `INSERT INTO country_registry.school_country
  (school_id, country_id, effective_from, source, recorded_by)
SELECT s.id, c.id, $2::date, 'legacy_uganda', $1
FROM school s CROSS JOIN country_registry.country c
WHERE c.code = 'UG' AND NOT EXISTS (SELECT 1 FROM country_registry.school_country x WHERE x.school_id = s.id)`, by, LegacySince); err != nil {
		return out, err
	}
	if err := exec("the accounts", &out.Memberships, `INSERT INTO country_registry.country_membership
  (id, user_id, country_id, is_default, effective_from, granted_by, grant_reason)
SELECT gen_random_uuid(), u.id, c.id, true, $2::date, $1, 'Every existing account works in Uganda'
FROM "user" u CROSS JOIN country_registry.country c
WHERE c.code = 'UG' AND NOT EXISTS (SELECT 1 FROM country_registry.country_membership x WHERE x.user_id = u.id)`, by, LegacySince); err != nil {
		return out, err
	}
	return out, nil
}
