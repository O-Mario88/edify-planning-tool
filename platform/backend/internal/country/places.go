package country

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// Phase 3, SSA (docs/migration/80-multi-country-phase-0.md §14): the
// registry's answers to "which regions", "which people" and "which country"
// as SQL fragments, for the readers that compared a country's name as text.

// RegionsIn is the SQL sub-select of the existing regions of the countries
// whose registry ids the placeholder ids holds (a text[] argument): those
// whose country name is one of the country's names in the registry.
func RegionsIn(ids string) string {
	return fmt.Sprintf(`(SELECT rr.id FROM region rr JOIN country_registry.country_alias ral ON ral.alias = btrim(rr.country)
  WHERE ral.country_id::text = ANY(%s))`, ids)
}

// UsersIn is the SQL sub-select of the account ids that work in the country
// whose registry id the placeholder id holds (text), as the existing
// country_user_ids reads a country's people. In a country whose roles are
// the existing profile's (Uganda) it is today's rule, the profile naming the
// country, kept to accounts that belong to it (BelongsTo); in a country whose
// roles come from the registry, the accounts with a membership of it in
// force.
func UsersIn(id string) string {
	return fmt.Sprintf(`(SELECT usp.user_id FROM staff_profile usp JOIN country_registry.country uc ON uc.id::text = %[1]s
  WHERE usp.user_id IS NOT NULL AND (
    (uc.roles_source = '%[2]s' AND usp.country = uc.name AND %[3]s)
    OR (uc.roles_source = '%[4]s' AND EXISTS (SELECT 1 FROM country_registry.country_membership um
      WHERE um.user_id = usp.user_id AND um.country_id = uc.id AND um.revoked_at IS NULL AND `+current("um")+`))))`,
		id, RolesFromProfile, BelongsTo("usp.user_id", id), RolesFromRegistry)
}

// SchoolCountryName is the SQL expression for the name of the country a
// school (aliased by school) belongs to in the registry (SchoolIn), or ""
// when it belongs to none: the country whose rules apply to it, where the
// existing code read its region's country name.
func SchoolCountryName(school string) string {
	return fmt.Sprintf(`COALESCE((SELECT sc_c.name FROM country_registry.country sc_c WHERE %s ORDER BY sc_c.code LIMIT 1), '')`,
		SchoolIn(school, "ARRAY[sc_c.id::text]"))
}

// ClusterIn is the SQL that a cluster (aliased by cluster, the existing
// cluster table) belongs to one of the countries whose registry ids the
// placeholder ids holds (a text[] argument): by its region, or by its
// district's region, whose country name is one of the country's names in
// the registry (docs/migration/80 §16). A cluster with neither belongs to
// no country, as in the existing cluster_queryset.
func ClusterIn(cluster, ids string) string {
	return fmt.Sprintf(`(EXISTS (SELECT 1 FROM region cr JOIN country_registry.country_alias cal ON cal.alias = btrim(cr.country)
    WHERE cr.id = %[1]s.region_id AND cal.country_id::text = ANY(%[2]s))
  OR EXISTS (SELECT 1 FROM district cd JOIN region cr ON cr.id = cd.region_id
    JOIN country_registry.country_alias cal ON cal.alias = btrim(cr.country)
    WHERE cd.id = %[1]s.district_id AND cal.country_id::text = ANY(%[2]s)))`, cluster, ids)
}

// PartnerIn is the SQL that a partner organisation (aliased by partner, the
// existing partner table) works in one of the countries whose registry ids
// the placeholder ids holds (a text[] argument): its recorded country in
// force (country_registry.partner_country, docs/migration/80 §17). A
// partner with no recorded country at all — one the existing application
// made after the registry was seeded — works in the country whose roles are
// the existing profile's (Uganda), as everything that application holds
// does; a partner whose recorded countries have all ended works in none.
func PartnerIn(partner, ids string) string {
	return fmt.Sprintf(`(EXISTS (SELECT 1 FROM country_registry.partner_country pc
    WHERE pc.partner_id = %[1]s.id AND pc.country_id::text = ANY(%[2]s) AND `+current("pc")+`)
  OR (NOT EXISTS (SELECT 1 FROM country_registry.partner_country pc WHERE pc.partner_id = %[1]s.id)
    AND EXISTS (SELECT 1 FROM country_registry.country pcc WHERE pcc.id::text = ANY(%[2]s) AND pcc.roles_source = '%[3]s')))`,
		partner, ids, RolesFromProfile)
}

// CurrencyOf is the ISO currency the country w keeps its money in, from its
// settings in force (country_config_version); "" when w is nil or the
// country has no settings in force yet.
func CurrencyOf(ctx context.Context, q Querier, w *Work) (string, error) {
	if w == nil {
		return "", nil
	}
	var code string
	err := q.QueryRow(ctx, `SELECT v.currency_code FROM country_registry.country_config_version v
WHERE v.country_id = $1::uuid AND `+current("v")+` ORDER BY v.effective_from DESC LIMIT 1`, w.ID).Scan(&code)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("country: reading %s's currency: %w", w.Code, err)
	}
	return code, nil
}

// AccountIn is the SQL that the account whose id the expression user names
// works in the country whose registry id the placeholder id holds (text):
// it has a membership of it in force, or — an account the existing
// application made after the registry was seeded — no membership at all and
// the country's roles are the existing profile's (Uganda), as everything
// that application holds is Uganda's (docs/migration/80, §19).
func AccountIn(user, id string) string {
	return fmt.Sprintf(`(EXISTS (SELECT 1 FROM country_registry.country_membership am
    WHERE am.user_id = %[1]s AND am.country_id::text = %[2]s AND am.revoked_at IS NULL AND `+current("am")+`)
  OR (NOT EXISTS (SELECT 1 FROM country_registry.country_membership am WHERE am.user_id = %[1]s)
    AND EXISTS (SELECT 1 FROM country_registry.country ac WHERE ac.id::text = %[2]s AND ac.roles_source = '%[3]s')))`,
		user, id, RolesFromProfile)
}

// ActivityHeldIn is ActivityIn for the money pages, which the existing
// application reads across the whole platform rather than by country:
// work that ActivityIn places in no country at all (no school, no cluster
// and no country-bound responsible person) is held by the country whose
// roles are the existing profile's (Uganda), as everything that application
// holds is Uganda's (docs/migration/80, §19). Planning and SSA readers keep
// ActivityIn, as the existing activity_country_q leaves such work out.
func ActivityHeldIn(a, s, cl, ids string) string {
	return fmt.Sprintf(`(%s OR (NOT %s AND EXISTS (SELECT 1 FROM country_registry.country hc
    WHERE hc.id::text = ANY(%s) AND hc.roles_source = '%s')))`,
		ActivityIn(a, s, cl, ids), ActivityIn(a, s, cl, "ARRAY(SELECT anyc.id::text FROM country_registry.country anyc)"), ids, RolesFromProfile)
}

// ActivityRowIn is ActivityHeldIn for a reader that holds only an
// activity's id (the expression activity, e.g. an advance's activity_id):
// that activity, with its school and cluster, belongs to one of the
// countries whose registry ids the placeholder ids holds (a text[]
// argument).
func ActivityRowIn(activity, ids string) string {
	return fmt.Sprintf(`EXISTS (SELECT 1 FROM activity rax LEFT JOIN school ras ON ras.id = rax.school_id
    LEFT JOIN cluster racl ON racl.id = rax.cluster_id WHERE rax.id = %s AND %s)`, activity, ActivityHeldIn("rax", "ras", "racl", ids))
}

// SchoolHeldIn is SchoolIn for readers the existing application serves
// across the whole platform (school loans): a school the registry places in
// no country at all — or none, for a record not matched to a school — is held
// by the country whose roles are the existing profile's (Uganda), as with
// ActivityHeldIn (docs/migration/80, §20).
func SchoolHeldIn(school, ids string) string {
	return fmt.Sprintf(`(%s OR (NOT %s AND EXISTS (SELECT 1 FROM country_registry.country shc
    WHERE shc.id::text = ANY(%s) AND shc.roles_source = '%s')))`,
		SchoolIn(school, ids), SchoolIn(school, "ARRAY(SELECT anys.id::text FROM country_registry.country anys)"), ids, RolesFromProfile)
}

// heldCode is the code of the country that holds what no country's registry
// places: the country whose roles are the existing profile's (Uganda), as
// everything the existing application holds is (owner decision 2), and
// Uganda's code itself before the registry is seeded.
var heldCode = `(SELECT hcc.code FROM country_registry.country hcc WHERE hcc.roles_source = '` + RolesFromProfile + `' ORDER BY hcc.code LIMIT 1), 'UG'`

// HeldCode is the SQL for the holding country's code.
var HeldCode = `COALESCE(` + heldCode + `)`

// SchoolCountryCode is the SQL for the code of the country a record at the
// school whose id the expression school names is recorded under, for the
// database's country guard (docs/migration/80 §23): the school's registry
// country, else — a school no country holds, or no school yet — the
// holding country's (SchoolHeldIn).
func SchoolCountryCode(school string) string {
	return `COALESCE((SELECT scc.code FROM country_registry.country scc JOIN school scs ON scs.id = CAST(` + school +
		` AS varchar) WHERE ` + SchoolIn("scs", "ARRAY[scc.id::text]") + ` ORDER BY scc.code LIMIT 1), ` + heldCode + `)`
}

// ClusterCountryCode is SchoolCountryCode for a record of the cluster whose
// id the expression cluster names: the cluster's country (ClusterIn), else
// the holding country's.
func ClusterCountryCode(cluster string) string {
	return `COALESCE((SELECT ccc.code FROM country_registry.country ccc JOIN cluster ccs ON ccs.id = CAST(` + cluster +
		` AS varchar) WHERE ` + ClusterIn("ccs", "ARRAY[ccc.id::text]") + ` ORDER BY ccc.code LIMIT 1), ` + heldCode + `)`
}
