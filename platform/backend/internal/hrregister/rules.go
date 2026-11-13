// Package hrregister is the HR programme registers: the Human Capital pages
// apps.frontend.views.hr_views draws with `_render_workspace`
// (pages/hr/module_workspace.html and partials/hr/module_register.html) and
// the app's feed reads (apps.mobile_feed). Each register is a breadcrumb,
// the workspace strip, a line of context figures and a table of records.
// The registers Go answers are listed in rules.json; the others stay with
// the existing application until they are ported.
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_hr_register_rules`;
// apps/hr/test_hr_register_rules_export.py fails when the two differ. Every
// save a register's buttons open stays with the existing application.
package hrregister

import (
	_ "embed"
	"encoding/json"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on one register.
type Role struct {
	// Page opens the register at all.
	Page bool `json:"page"`
	// Strip is the workspace strip above the register, or nil.
	Strip *decisionlog.Strip `json:"strip"`
	// Drawers are the header buttons' drawers the role may open.
	Drawers []string `json:"drawers"`
}

// Page is one register's doors.
type Page struct {
	Roles map[string]Role `json:"roles"`
}

// Rules are the registers' vocabularies.
type Rules struct {
	Pages             map[string]Page   `json:"pages"`
	OnboardingStates  map[string]string `json:"onboarding_states"`
	MetricLabels      map[string]string `json:"metric_labels"`
	HelperFigureChars int               `json:"helper_figure_chars"`
	PageSize          int               `json:"page_size"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Pages) == 0 || len(r.OnboardingStates) == 0 ||
		len(r.MetricLabels) == 0 || r.HelperFigureChars <= 0 || r.PageSize <= 0 {
		panic(fmt.Sprintf("hrregister: the embedded rules are unreadable: %v", err))
	}
	return r
}
