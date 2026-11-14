package todos

import (
	"context"
	"testing"
)

// The existing may_manage_partner_users lets any superuser through, whatever
// their role, so it offers a superuser of any role the "Configure Partner
// Users" row. Go decides by role alone: a role outside the setup roles gets
// no row (and is no longer passed on for it) (owner, 2026-11-13: "Can you fix
// those from the go side").
func TestPartnerLoginSetupIsDecidedByRoleAlone(t *testing.T) {
	for _, role := range []string{"CCEO", "Program Lead", "ImpactAssessment"} {
		if contains(rules.Admin.PartnerUserSetupRoles, role) {
			t.Fatalf("%s is a setup role; pick another for this test", role)
		}
		rows, err := partnerUserSetupTodos(context.Background(), nil, &reader{role: role})
		if err != nil || len(rows) != 0 {
			t.Fatalf("%s: rows %v, err %v; want no row and no pass-on", role, rows, err)
		}
	}
}
