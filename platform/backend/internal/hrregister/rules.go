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
	// Links are the header link buttons' pages the role may open.
	Links []string `json:"links"`
}

// Page is one register's doors.
type Page struct {
	Roles map[string]Role `json:"roles"`
}

// Rules are the registers' vocabularies.
type Rules struct {
	Pages            map[string]Page   `json:"pages"`
	OnboardingStates map[string]string `json:"onboarding_states"`
	// The labels of a recognition's category and a safety incident's
	// category, severity and status.
	RecognitionCategories map[string]string `json:"recognition_categories"`
	SafetyCategories      map[string]string `json:"safety_categories"`
	Severities            map[string]string `json:"severities"`
	SafetyStatuses        map[string]string `json:"safety_statuses"`
	// The labels of an onboarding plan's status and an exit's reason, and
	// the reasons that are voluntary (VOLUNTARY_EXIT_REASONS).
	OnboardingStatuses   map[string]string `json:"onboarding_statuses"`
	ExitReasons          map[string]string `json:"exit_reasons"`
	VoluntaryExitReasons []string          `json:"voluntary_exit_reasons"`
	// The labels of an application's stage.
	ApplicationStages map[string]string `json:"application_stages"`
	// The labels of an employee's compliance status.
	ComplianceStatuses map[string]string `json:"compliance_statuses"`
	// The labels of a document's type and status.
	DocumentTypes    map[string]string `json:"document_types"`
	DocumentStatuses map[string]string `json:"document_statuses"`
	// The labels of a recovery plan's type, cause and status.
	RecoveryPlanTypes map[string]string `json:"recovery_plan_types"`
	RecoveryCauses    map[string]string `json:"recovery_causes"`
	RecoveryStatuses  map[string]string `json:"recovery_statuses"`
	// The labels of a performance review's stage, type and rating.
	ReviewStages       map[string]string `json:"review_stages"`
	ReviewTypes        map[string]string `json:"review_types"`
	PerformanceRatings map[string]string `json:"performance_ratings"`
	// The labels of a compensation record's status and medical cover.
	CompensationStatuses map[string]string `json:"compensation_statuses"`
	MedicalCovers        map[string]string `json:"medical_covers"`
	// A pulse survey's status labels, its statements' keys in order and the
	// fewest answers before a result is shown.
	PulseStatuses     map[string]string `json:"pulse_statuses"`
	PulseQuestions    []string          `json:"pulse_questions"`
	PulseMinResponses int               `json:"pulse_min_responses"`
	// Reviews are the roles each role is the performance reviewer for.
	Reviews           map[string][]string `json:"reviews"`
	MetricLabels      map[string]string   `json:"metric_labels"`
	HelperFigureChars int                 `json:"helper_figure_chars"`
	PageSize          int                 `json:"page_size"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Pages) == 0 || len(r.OnboardingStates) == 0 || len(r.RecognitionCategories) == 0 || len(r.SafetyCategories) == 0 ||
		len(r.Severities) == 0 || len(r.SafetyStatuses) == 0 || len(r.OnboardingStatuses) == 0 ||
		len(r.ExitReasons) == 0 || len(r.VoluntaryExitReasons) == 0 || len(r.ApplicationStages) == 0 || len(r.ComplianceStatuses) == 0 || len(r.DocumentTypes) == 0 || len(r.DocumentStatuses) == 0 ||
		len(r.RecoveryPlanTypes) == 0 || len(r.RecoveryCauses) == 0 || len(r.RecoveryStatuses) == 0 || len(r.Reviews) == 0 ||
		len(r.ReviewStages) == 0 || len(r.PulseStatuses) == 0 || len(r.PulseQuestions) == 0 || r.PulseMinResponses <= 0 || len(r.CompensationStatuses) == 0 || len(r.MedicalCovers) == 0 || len(r.ReviewTypes) == 0 || len(r.PerformanceRatings) == 0 ||
		len(r.MetricLabels) == 0 || r.HelperFigureChars <= 0 || r.PageSize <= 0 {
		panic(fmt.Sprintf("hrregister: the embedded rules are unreadable: %v", err))
	}
	return r
}

// labelOf is get_<field>_display: the value's label, else the value itself.
func labelOf(labels map[string]string, value string) string {
	if l, ok := labels[value]; ok {
		return l
	}
	return value
}
