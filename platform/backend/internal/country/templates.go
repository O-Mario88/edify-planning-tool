package country

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// AdminLevelTemplate defines one administrative hierarchy level for a country.
type AdminLevelTemplate struct {
	CanonicalType string
	LocalLabel    string
	Level         int
	Required      bool
}

// CountryTemplate holds the initial configuration and geography levels for an
// expansion country (Kenya P3, Rwanda P4, Ethiopia P5). Countries remain in
// Draft state until explicitly validated and activated by leadership.
type CountryTemplate struct {
	Code               string
	Name               string
	DefaultLanguage    string
	Languages          []string
	CurrencyCode       string
	CurrencyMinorUnits int
	TimeZone           string
	DateFormat         string
	Calendars          []string
	FYStartMonth       int
	Levels             []AdminLevelTemplate
}

// ExpansionTemplates defines the country-specific configuration for Kenya,
// Rwanda, and Ethiopia per the Edify Global Multi-Country Architecture.
var ExpansionTemplates = []CountryTemplate{
	{
		Code:               "KE",
		Name:               "Kenya",
		DefaultLanguage:    "en",
		Languages:          []string{"en", "sw"},
		CurrencyCode:       "KES",
		CurrencyMinorUnits: 2,
		TimeZone:           "Africa/Nairobi",
		DateFormat:         "j M Y",
		Calendars:          []string{"gregorian"},
		FYStartMonth:       10,
		Levels: []AdminLevelTemplate{
			{CanonicalType: "county", LocalLabel: "County", Level: 1, Required: true},
			{CanonicalType: "sub_county", LocalLabel: "Sub-county", Level: 2, Required: true},
			{CanonicalType: "ward", LocalLabel: "Ward", Level: 3, Required: false},
		},
	},
	{
		Code:               "RW",
		Name:               "Rwanda",
		DefaultLanguage:    "en",
		Languages:          []string{"en", "rw", "fr"},
		CurrencyCode:       "RWF",
		CurrencyMinorUnits: 0,
		TimeZone:           "Africa/Kigali",
		DateFormat:         "j M Y",
		Calendars:          []string{"gregorian"},
		FYStartMonth:       10,
		Levels: []AdminLevelTemplate{
			{CanonicalType: "province", LocalLabel: "Province", Level: 1, Required: true},
			{CanonicalType: "district", LocalLabel: "District", Level: 2, Required: true},
			{CanonicalType: "sector", LocalLabel: "Sector", Level: 3, Required: true},
			{CanonicalType: "cell", LocalLabel: "Cell", Level: 4, Required: false},
			{CanonicalType: "village", LocalLabel: "Village", Level: 5, Required: false},
		},
	},
	{
		Code:               "ET",
		Name:               "Ethiopia",
		DefaultLanguage:    "am",
		Languages:          []string{"am", "om", "en"},
		CurrencyCode:       "ETB",
		CurrencyMinorUnits: 2,
		TimeZone:           "Africa/Addis_Ababa",
		DateFormat:         "j M Y",
		Calendars:          []string{"ethiopian", "gregorian"},
		FYStartMonth:       10,
		Levels: []AdminLevelTemplate{
			{CanonicalType: "regional_state", LocalLabel: "Regional State", Level: 1, Required: true},
			{CanonicalType: "zone", LocalLabel: "Zone", Level: 2, Required: true},
			{CanonicalType: "woreda", LocalLabel: "Woreda", Level: 3, Required: true},
			{CanonicalType: "kebele", LocalLabel: "Kebele", Level: 4, Required: false},
		},
	},
}

// SeededTemplates reports how many config versions and admin levels were added.
type SeededTemplates struct {
	Configs int64
	Levels  int64
}

// SeedExpansionTemplates idempotently populates v1 configuration and geography
// hierarchy levels for Kenya, Rwanda, and Ethiopia without activating them
// (they stay in Draft state until leadership validation).
func SeedExpansionTemplates(ctx context.Context, tx pgx.Tx, by string) (SeededTemplates, error) {
	var out SeededTemplates
	if err := WriteFor(ctx, tx, true); err != nil {
		return out, err
	}
	if _, err := tx.Exec(ctx, `SELECT set_config('edify.write_countries', string_agg(id::text, ','), true)
FROM country_registry.country`); err != nil {
		return out, fmt.Errorf("country: declaring expansion countries: %w", err)
	}
	for _, tpl := range ExpansionTemplates {
		tag, err := tx.Exec(ctx, `INSERT INTO country_registry.country_config_version
  (id, country_id, version, default_language, languages, currency_code, currency_minor_units, time_zone,
   date_format, calendars, fy_start_month, effective_from, changed_by, change_reason)
SELECT gen_random_uuid(), id, 1, $2, $3, $4, $5, $6, $7, $8, $9, current_date, $10,
  'Initial Edify Global country template (' || $1 || ')'
FROM country_registry.country WHERE code = $1
ON CONFLICT (country_id, version) DO NOTHING`,
			tpl.Code, tpl.DefaultLanguage, tpl.Languages, tpl.CurrencyCode, tpl.CurrencyMinorUnits,
			tpl.TimeZone, tpl.DateFormat, tpl.Calendars, tpl.FYStartMonth, by)
		if err != nil {
			return out, fmt.Errorf("country: seeding %s config template: %w", tpl.Code, err)
		}
		out.Configs += tag.RowsAffected()

		for _, lvl := range tpl.Levels {
			ltag, err := tx.Exec(ctx, `INSERT INTO country_registry.admin_unit_type
  (id, country_id, canonical_type, local_label, level, is_required, effective_from, created_by)
SELECT gen_random_uuid(), c.id, $2, $3, $4, $5, current_date, $6
FROM country_registry.country c
WHERE c.code = $1 AND NOT EXISTS (
  SELECT 1 FROM country_registry.admin_unit_type t
  WHERE t.country_id = c.id AND t.canonical_type = $2 AND t.effective_to IS NULL
)`, tpl.Code, lvl.CanonicalType, lvl.LocalLabel, lvl.Level, lvl.Required, by)
			if err != nil {
				return out, fmt.Errorf("country: seeding %s level %s: %w", tpl.Code, lvl.CanonicalType, err)
			}
			out.Levels += ltag.RowsAffected()
		}
	}
	return out, nil
}
