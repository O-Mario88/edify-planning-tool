// Package qualityflags is Quality Flags (/quality-checks): the flags a
// Country Director raises to a Programme Lead, with the form that raises one
// and the register of the reader's flags, as the existing page draws them
// (apps.frontend.views.extended_views.quality_checks_view,
// apps.flags.services and pages/quality_checks/index.html) and the app's feed
// reads them (apps.mobile_feed). Raising, acknowledging and resolving stay
// with the existing application.
//
// The doors, roles, labels and limit are exported to rules.json by
// `manage.py export_quality_flags_rules`;
// apps/flags/test_quality_flags_rules_export.py fails when the two differ.
package qualityflags

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	Page bool `json:"page"`
	// Raises is shown the form that raises a flag (the Country Director,
	// Admin).
	Raises bool `json:"raises"`
	// Acts is shown the Actions column (the Programme Lead, Admin).
	Acts bool `json:"acts"`
}

var rules = func() (r struct {
	Roles map[string]Role `json:"roles"`
	// MonitorRoles read every flag (country-bound for Impact Assessment)
	// rather than the ones they raised or were assigned.
	MonitorRoles []string          `json:"monitor_roles"`
	Statuses     map[string]string `json:"statuses"`
	Limit        int               `json:"limit"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.Statuses) == 0 || r.Limit == 0 {
		panic(fmt.Sprintf("qualityflags: the embedded rules are unreadable: %v", err))
	}
	return r
}()
