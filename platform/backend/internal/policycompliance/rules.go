// Package policycompliance is Policy and Manual Compliance
// (/policy-compliance): who in the reader's scope has answered the policies
// required of them, with their reading time and viewer completion, as the
// existing page draws it (apps.documents.views.compliance_view,
// apps.documents.compliance.PolicyComplianceService and
// pages/documents/compliance.html) and the app's feed reads it. Answering a
// policy comment stays with the existing application, and a reader whose
// comment queue holds comments is passed on to it (their private text is not
// read here).
//
// The doors, strips, labels and limits are exported to rules.json by
// `manage.py export_policy_compliance_rules`;
// apps/documents/test_policy_compliance_rules_export.py fails when the two
// differ.
package policycompliance

import (
	_ "embed"
	"encoding/json"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	Page bool `json:"page"`
	// Strip is the workspace strip above the table, or nil.
	Strip *decisionlog.Strip `json:"strip"`
	// Comments reads the policy comment queue (policies.review_comments).
	Comments bool `json:"comments"`
	// ScopeNote is the line under the title (_scope_note).
	ScopeNote string `json:"scope_note"`
}

var rules = func() (r struct {
	Roles              map[string]Role   `json:"roles"`
	MetricLabels       map[string]string `json:"metric_labels"`
	MetricDrilldowns   map[string]string `json:"metric_drilldowns"`
	ReadableStatuses   []string          `json:"readable_statuses"`
	States             map[string]string `json:"states"`
	CompletionLabels   map[string]string `json:"completion_labels"`
	RowLimit           int               `json:"row_limit"`
	PageSize           int               `json:"page_size"`
	QueryKeysNotPassed []string          `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.MetricLabels) != 2 || len(r.States) == 0 ||
		len(r.CompletionLabels) == 0 || r.RowLimit == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("policycompliance: the embedded rules are unreadable: %v", err))
	}
	return r
}()

const (
	acceptedKey = "policy_acknowledgements_accepted"
	overdueKey  = "policy_acknowledgements_overdue"
)
