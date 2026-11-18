package country

import "fmt"

// Phase 3, planning (docs/migration/80-multi-country-phase-0.md §13): the
// clauses that keep planning's records, people and settings to the country
// a request is made in, read through the registry rather than by comparing
// a country's name as text.

// SettingsName is the name the existing planning tables key a country's
// own rows by (cost_catalogue.country, fiscal_year_planning_policy.country,
// calendar_block.country, country_annual_budget.country_id: "Uganda").
// existing is the name the existing application uses, which is Uganda's;
// it stays the key wherever the country's roles are the existing profile's
// or the request is made in no Active country, so Uganda reads exactly the
// rows it reads today. A country whose roles come from the registry reads
// its own rows by its own name, and finds none until they are recorded.
func SettingsName(w *Work, existing string) string {
	if w.FromRegistry() {
		return w.Name
	}
	return existing
}

// ActivityIn is the SQL that an activity (aliased a), with its school s and
// cluster cl joined to it (either may be absent), belongs to one of the
// countries whose registry ids the placeholder ids holds (a text[]
// argument). It is the existing activity_country_q read through the
// registry: the school's country (SchoolIn: explicit, else its region's,
// else its holder's); else the cluster's, through its region or its
// district's region; else, for work with neither a school nor a cluster,
// the country its responsible person's profile names. The existing rule
// also put work at a school with no region and no country-bound holder in
// every country; here such a school is in the country the registry
// records for it, or none (owner decision 3, §8).
func ActivityIn(a, s, cl, ids string) string {
	return fmt.Sprintf(`((%[2]s.id IS NOT NULL AND %[4]s)
 OR EXISTS (SELECT 1 FROM region r JOIN country_registry.country_alias al ON al.alias = btrim(r.country)
     WHERE r.id = %[3]s.region_id AND al.country_id::text = ANY(%[5]s))
 OR EXISTS (SELECT 1 FROM district d JOIN region r ON r.id = d.region_id
     JOIN country_registry.country_alias al ON al.alias = btrim(r.country)
     WHERE d.id = %[3]s.district_id AND al.country_id::text = ANY(%[5]s))
 OR (%[1]s.school_id IS NULL AND %[1]s.cluster_id IS NULL AND EXISTS (
     SELECT 1 FROM staff_profile rsp JOIN country_registry.country_alias al ON al.alias = btrim(rsp.country)
     WHERE rsp.id = %[1]s.responsible_staff_id AND rsp.deleted_at IS NULL AND al.country_id::text = ANY(%[5]s))))`,
		a, s, cl, SchoolIn(s, ids), ids)
}

// BelongsTo is the SQL that the account whose id the expression user names
// works in the country whose registry id the placeholder id holds (text):
// it has a membership of it in force, or no membership at all (an account
// the existing application made after the registry was seeded, which works
// in its profile's country). A profile-based roster adds it to its own
// country test, so a person who now belongs only to another country leaves
// it.
func BelongsTo(user, id string) string {
	return fmt.Sprintf(`(EXISTS (SELECT 1 FROM country_registry.country_membership bm
    WHERE bm.user_id = %[1]s AND bm.country_id::text = %[2]s AND bm.revoked_at IS NULL AND `+current("bm")+`)
  OR NOT EXISTS (SELECT 1 FROM country_registry.country_membership bm WHERE bm.user_id = %[1]s))`, user, id)
}

// HoldsRoleIn is the SQL that the account whose id the expression user
// names holds, in the country whose registry id the placeholder id holds
// (text), one of the roles the placeholder roles holds (a text array):
// assigned there, not revoked, under a membership in force. It is how a
// country whose roles come from the registry finds its people.
func HoldsRoleIn(user, id, roles string) string {
	return fmt.Sprintf(`EXISTS (SELECT 1 FROM country_registry.country_role_assignment hr
    JOIN country_registry.country_membership hm ON hm.id = hr.membership_id
    WHERE hr.user_id = %[1]s AND hr.country_id::text = %[2]s AND hr.revoked_at IS NULL
      AND hr.role_name = ANY(%[3]s) AND hm.revoked_at IS NULL AND `+current("hm")+`)`, user, id, roles)
}

// RolesIn is the SQL for the roles the account whose id the expression user
// names holds in the country whose registry id the placeholder id holds
// (text), as a text array, oldest first: what a registry country's roster
// reads in place of the existing account's roles.
func RolesIn(user, id string) string {
	return fmt.Sprintf(`ARRAY(SELECT hr.role_name FROM country_registry.country_role_assignment hr
    JOIN country_registry.country_membership hm ON hm.id = hr.membership_id
    WHERE hr.user_id = %[1]s AND hr.country_id::text = %[2]s AND hr.revoked_at IS NULL
      AND hm.revoked_at IS NULL AND `+current("hm")+` ORDER BY hr.granted_at, hr.role_name)::varchar[]`, user, id)
}

// Roster is how a planning roster reads its people (staff_profile sp and
// account u) in a country: the expressions for each person's roles and
// active role, and the condition that they hold one of the roles passed as
// the first argument and work in the country, with the arguments, the
// roles first.
type Roster struct {
	Roles, Active, Where string
	Args                 []any
}

// RosterIn is the roster of the people holding one of roles in the country
// named name with registry id id. With no name the roster is unbounded and
// reads the existing accounts' roles, as today. In a country whose roles are
// the existing profile's (fromRegistry false: Uganda) it is today's rule,
// the profile naming the country or none, kept to accounts that belong to
// it (BelongsTo). In a country whose roles come from the registry it is the
// people holding the role there (HoldsRoleIn), with the roles they hold
// there.
func RosterIn(name, id string, fromRegistry bool, roles []string) Roster {
	r := Roster{Roles: `COALESCE(u.roles, '{}')`, Active: `COALESCE(u.active_role, '')`,
		Where: `(u.roles && $1::varchar[] OR u.active_role = ANY($1))`, Args: []any{roles}}
	switch {
	case name == "":
	case fromRegistry:
		r.Args = append(r.Args, id)
		r.Roles, r.Active, r.Where = RolesIn("u.id", "$2"), `''`, HoldsRoleIn("u.id", "$2", "$1::varchar[]")
	default:
		r.Args = append(r.Args, name, id)
		r.Where += ` AND (sp.country = $2 OR sp.country = '') AND ` + BelongsTo("u.id", "$3")
	}
	return r
}
