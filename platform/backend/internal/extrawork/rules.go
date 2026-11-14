// Package extrawork is Extra Assigned Work (/extra-work): the assignments
// handed to the reader and their performance lane, the ones waiting on the
// reader's review, the ones the reader handed out and the ones on the
// reader's team the Country Director owns, as the existing page draws them
// (apps.frontend.views.extra_work_views.extra_work_page,
// apps.hr.extra_work.performance_summary and pages/hr/extra_work.html) and
// the app's feed reads them (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_extra_work_rules`;
// apps/hr/test_extra_work_rules_export.py fails when the two differ. The
// page's saves (Start, Submit Result, Verify, Return, Cancel, Assign) stay
// with the existing application.
package extrawork

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	// Page opens Extra Assigned Work at all.
	Page bool `json:"page"`
	// Strip is the workspace strip above the page, or nil.
	Strip *decisionlog.Strip `json:"strip"`
	// CanAssign shows the Assign Extra Work button (extra_work.ASSIGNER_ROLES).
	CanAssign bool `json:"can_assign"`
}

// Limits are how many rows each section reads.
type Limits struct {
	Mine         int `json:"mine"`
	AssignedByMe int `json:"assigned_by_me"`
	ToReview     int `json:"to_review"`
	Monitoring   int `json:"monitoring"`
}

// Cuts are the lengths the template cuts each text to (|truncatechars).
type Cuts struct {
	Instruction  int `json:"instruction"`
	ReturnReason int `json:"return_reason"`
	Outcome      int `json:"outcome"`
	Evidence     int `json:"evidence"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles              map[string]Role   `json:"roles"`
	StatusLabels       map[string]string `json:"status_labels"`
	OpenStatuses       []string          `json:"open_statuses"`
	Limits             Limits            `json:"limits"`
	Cuts               Cuts              `json:"cuts"`
	SummaryShows       int               `json:"summary_shows"`
	PageParam          string            `json:"page_param"`
	PageSize           int               `json:"page_size"`
	QueryKeysNotPassed []string          `json:"query_keys_not_passed"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || len(r.StatusLabels) == 0 ||
		len(r.OpenStatuses) == 0 || r.Limits.Mine <= 0 || r.Limits.AssignedByMe <= 0 || r.Limits.ToReview <= 0 ||
		r.Limits.Monitoring <= 0 || r.Cuts.Instruction <= 0 || r.Cuts.ReturnReason <= 0 || r.Cuts.Outcome <= 0 ||
		r.Cuts.Evidence <= 0 || r.SummaryShows <= 0 || r.PageParam == "" || r.PageSize <= 0 {
		panic(fmt.Sprintf("extrawork: the embedded rules are unreadable: %v", err))
	}
	return r
}

// open is ExtraAssignment.OPEN_STATUSES: work not yet handed in.
func open(status string) bool { return slices.Contains(rules.OpenStatuses, status) }

// label is get_status_display: the status's label, else the status itself.
func label(status string) string {
	if l, ok := rules.StatusLabels[status]; ok {
		return l
	}
	return status
}
