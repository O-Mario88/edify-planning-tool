// Package projectcapacity is Project Capacity (/projects/capacity): the
// Project Coordinator's school allocations, one project a tab, each staff
// member's maximum, the schools they hold, what is left, and their year's
// planned visits against their role's ceiling, as the existing page draws
// them (apps.frontend.views.project_capacity_views.project_capacity_view,
// apps.projects.capacity and pages/projects/capacity.html) and the app's feed
// reads them (apps.mobile_feed). Setting and editing an allocation stay with
// the existing application.
//
// The doors, strips, statuses and limits are exported to rules.json by
// `manage.py export_project_capacity_rules`;
// apps/projects/test_project_capacity_rules_export.py fails when the two
// differ.
package projectcapacity

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
	// Strip is the workspace strip above the page, or nil.
	Strip *decisionlog.Strip `json:"strip"`
	// StaffLinks makes a staff member's name the way into their profile.
	StaffLinks bool `json:"staff_links"`
}

// Block is why a school may not leave a project now (capacity.WithdrawalBlock).
type Block struct {
	Code    string `json:"code"`
	Title   string `json:"title"`
	Message string `json:"message"`
}

var rules = func() (r struct {
	Roles map[string]Role `json:"roles"`
	// LiveStatuses are the projects the page lists; OpenStatuses the ones
	// that still take new schools (any other reads "Blocked").
	LiveStatuses       []string `json:"live_statuses"`
	OpenStatuses       []string `json:"open_statuses"`
	NearCapacityShare  float64  `json:"near_capacity_share"`
	PageSize           int      `json:"page_size"`
	QueryKeysNotPassed []string `json:"query_keys_not_passed"`
	// What the Set Capacity and Withdraw School forms read.
	EligibleStaffRoles    []string            `json:"eligible_staff_roles"`
	WithdrawalReasons     [][2]string         `json:"withdrawal_reasons"`
	WithdrawalStageOrder  []string            `json:"withdrawal_stage_order"`
	WithdrawalStatuses    map[string][]string `json:"withdrawal_statuses"`
	WithdrawalBlocks      map[string]Block    `json:"withdrawal_blocks"`
	PartnerReturnedStatus string              `json:"partner_returned_status"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.LiveStatuses) == 0 || r.PageSize == 0 || r.NearCapacityShare == 0 {
		panic(fmt.Sprintf("projectcapacity: the embedded rules are unreadable: %v", err))
	}
	return r
}()
