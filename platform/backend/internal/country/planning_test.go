package country

import (
	"strings"
	"testing"
)

func TestSettingsName(t *testing.T) {
	uganda := &Work{Country: Country{Name: "Uganda"}, RolesSource: RolesFromProfile}
	kenya := &Work{Country: Country{Name: "Kenya"}, RolesSource: RolesFromRegistry}
	for name, c := range map[string]struct {
		w    *Work
		want string
	}{
		"no Active country keeps Uganda's rows": {nil, "Uganda"},
		"Uganda keeps its rows":                 {uganda, "Uganda"},
		"Kenya reads its own":                   {kenya, "Kenya"},
	} {
		if got := SettingsName(c.w, "Uganda"); got != c.want {
			t.Errorf("%s: %q, want %q", name, got, c.want)
		}
	}
}

func TestRosterIn(t *testing.T) {
	roles := []string{"Program Lead", "CCEO"}
	unbounded := RosterIn("", "", false, roles)
	if len(unbounded.Args) != 1 || unbounded.Where != `(u.roles && $1::varchar[] OR u.active_role = ANY($1))` ||
		unbounded.Roles != `COALESCE(u.roles, '{}')` {
		t.Errorf("unbounded: %+v", unbounded)
	}
	uganda := RosterIn("Uganda", "ug-id", false, roles)
	if len(uganda.Args) != 3 || uganda.Args[1] != "Uganda" || uganda.Args[2] != "ug-id" ||
		!strings.HasPrefix(uganda.Where, unbounded.Where+` AND (sp.country = $2 OR sp.country = '') AND `) ||
		!strings.Contains(uganda.Where, "country_membership") {
		t.Errorf("Uganda keeps today's rule, bounded to its members: %+v", uganda)
	}
	kenya := RosterIn("Kenya", "ke-id", true, roles)
	if len(kenya.Args) != 2 || kenya.Args[1] != "ke-id" || kenya.Active != `''` ||
		!strings.Contains(kenya.Where, "country_role_assignment") || strings.Contains(kenya.Where, "u.roles") ||
		!strings.Contains(kenya.Roles, "country_role_assignment") {
		t.Errorf("Kenya reads the roles held there: %+v", kenya)
	}
}

func TestActivityInReadsTheRegistry(t *testing.T) {
	sql := ActivityIn("a", "s", "cl", "$4")
	for _, want := range []string{"country_registry.school_country", "cl.region_id", "cl.district_id", "a.responsible_staff_id", "ANY($4)"} {
		if !strings.Contains(sql, want) {
			t.Errorf("ActivityIn lacks %q", want)
		}
	}
	if strings.Contains(sql, "account_owner_id IS NULL OR") {
		t.Error("ActivityIn still places work at a school of no country in every country")
	}
}
