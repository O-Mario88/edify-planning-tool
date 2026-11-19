// Package adminpanel builds the Admin Panel's pages as the existing feed
// reads them: Workflow & Automation Rules (/admin-panel/workflow-rules:
// extended_views.admin_workflow_rules_view, pages/admin/workflow_rules.html),
// the reference list of the rules the system enforces in code; and School
// Upload History (/admin-panel/school-upload-history, upload_history.go);
// the Admin Dashboard (/admin-panel, hub.go); and the Audit Log
// (/admin-panel/audit-log, audit.go); and Geographical Location Setup
// (/admin-panel/region-district-setup, geography.go).
//
// The doors and the listed rules are exported to rules.json by `manage.py
// export_admin_panel_rules`; apps/frontend/test_admin_panel_rules_export.py
// fails when the two differ.
package adminpanel

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Pages         map[string][]string `json:"pages"`
	WorkflowRules [][2]string         `json:"workflow_rules"`
	// MissingLines is what the dashboard's missing cost lines count leaves
	// out (hub.go).
	MissingLines struct {
		ExemptStatuses          []string `json:"exempt_statuses"`
		CompanionGoneStatuses   []string `json:"companion_gone_statuses"`
		RepriceablePairStatuses []string `json:"repriceable_pair_statuses"`
		OnlineTrainingTypes     []string `json:"online_training_types"`
		OnlineMode              string   `json:"online_mode"`
	} `json:"missing_lines"`
	// DistrictProfileRoles may open a district's profile.
	DistrictProfileRoles []string `json:"district_profile_roles"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("adminpanel: reading rules.json: %v", err))
	}
	if len(r.Pages) == 0 || len(r.WorkflowRules) == 0 {
		panic("adminpanel: rules.json lacks the doors or the workflow rules")
	}
	return r
}()

// WorkflowRulesPath is Workflow & Automation Rules.
const WorkflowRulesPath = "/admin-panel/workflow-rules"

// Service builds the pages.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the pages over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers the Admin Panel's pages; any other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	roles, ok := rules.Pages[path]
	if !ok {
		return nil, false, nil
	}
	if !slices.Contains(roles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	switch path {
	case UploadHistoryPath:
		return s.uploadHistory(ctx, p)
	case HubPath:
		return s.hub(ctx)
	case AuditLogPath:
		return s.auditLog(ctx, query)
	case GeographyPath:
		return s.geography(ctx, p)
	}
	return workflowRules(), true, nil
}

func header(eyebrow, title, description string) *screensv1.PageHeader {
	return &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: description,
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
}

func page(h *screensv1.PageHeader, path string, blocks ...*screensv1.PageBlock) *screensv1.GetPageResponse {
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, Tabs: []*screensv1.PageTab{},
		Dialogs: []*screensv1.PageDialog{}, WebPath: path}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// workflowRules is the reference list: each rule, its key and Enforced.
func workflowRules() *screensv1.GetPageResponse {
	list := &screensv1.PageList{}
	for _, r := range rules.WorkflowRules {
		list.Items = append(list.Items, &screensv1.PageListItem{Title: r[1], Lines: []string{"Rule Key: " + r[0]},
			Badges: []*screensv1.PageBadge{{Text: "Enforced", Tone: "good"}}})
	}
	return page(header("Administration", "Workflow & Automation Rules",
		"Reference list of validation checks, planning bounds, and automatic budget creation rules enforced by the system"),
		WorkflowRulesPath,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_List{List: list}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{text("These rules are not configurable here"),
				text("Each rule above is enforced directly in application code (role/permission checks and closure-eligibility logic), not stored as a toggleable database setting. Changing this behavior requires a code change and deployment, not a switch on this page.")}}}})
}
