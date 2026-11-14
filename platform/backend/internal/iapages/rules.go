// Package iapages is the Impact Assessment review pages
// (apps.frontend.views.ia_views) as the app's feed reads them, starting with
// Duplicate Review (/ia/duplicates/). Their decisions (ignore, return, flag)
// stay with the existing application.
//
// The doors, the verification permission and the activity labels
// are exported to rules.json by `manage.py export_ia_pages_rules`;
// apps/activities/test_ia_pages_rules_export.py fails when the two differ.
package iapages

import (
	_ "embed"
	"encoding/json"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on one page (the IA pages draw no workspace
// strip).
type Role struct {
	Page bool `json:"page"`
	// Strip is the IA workspace strip (Sample Checks and the stories draw
	// one).
	Strip *decisionlog.Strip `json:"strip"`
}

var rules = func() (r struct {
	Pages map[string]struct {
		Roles map[string]Role `json:"roles"`
	} `json:"pages"`
	IAVerifyRoles []string          `json:"ia_verify_roles"`
	ActivityTypes map[string]string `json:"activity_types"`
	// ExportRoles are offered Returned Activities' and Verification
	// History's Export (the data-export permission).
	ExportRoles []string `json:"export_roles"`
	// RequiredEvidence and ProfileRequiredEvidence are the evidence kinds an
	// activity must carry, by type and by evidence profile
	// (apps.evidence.requirements.required_kinds_for_activity).
	RequiredEvidence        map[string][]string `json:"required_evidence"`
	ProfileRequiredEvidence map[string][]string `json:"profile_required_evidence"`
	// QueuePageSize is the partner queue's length (QUEUE_PAGE_SIZE).
	QueuePageSize int `json:"queue_page_size"`
	// Sample Checks: the share drawn, who may draw, the check methods'
	// labels and the samples' page size.
	SampleSharePct  int               `json:"sample_share_pct"`
	SampleDrawRoles []string          `json:"sample_draw_roles"`
	SampleMethods   map[string]string `json:"sample_methods"`
	SamplePageSize  int               `json:"sample_page_size"`
	// TablePageSize is each Verification Analytics table's page
	// (TABLE_PAGE_SIZE).
	TablePageSize int `json:"table_page_size"`
	// Most Significant Change: each story status and its label (in order),
	// the intervention labels, the SSA domains that are spiritual formation,
	// and the outcome-area statuses never offered and the approved one.
	StoryStatuses             [][2]string       `json:"story_statuses"`
	InterventionLabels        map[string]string `json:"intervention_labels"`
	SpiritualDomains          []string          `json:"spiritual_domains"`
	OutcomeAreaHiddenStatuses []string          `json:"outcome_area_hidden_statuses"`
	OutcomeAreaApprovedStatus string            `json:"outcome_area_approved_status"`
	// SchoolProfileRoles may open a school's profile.
	SchoolProfileRoles []string `json:"school_profile_roles"`
	// QueryKeysNotPassed are the query keys the feed never passes to a page.
	QueryKeysNotPassed []string `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Pages) == 0 || len(r.IAVerifyRoles) == 0 || len(r.ActivityTypes) == 0 {
		panic(fmt.Sprintf("iapages: the embedded rules are unreadable: %v", err))
	}
	return r
}()
