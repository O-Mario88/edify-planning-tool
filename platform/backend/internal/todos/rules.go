// Package todos is the To-Do page (/todos): the reader's derived action
// queue, its strip, its category and priority chips and its rows, identical
// ones grouped (owner, 2026-09-30), as the existing page draws them
// (apps.frontend.views.extended_views.todos_view,
// apps.command_center.todo_service.get_todos, todo_groups.group_identical,
// pages/todos/index.html and partials/todos/row.html) and the app's feed
// reads them (apps.mobile_feed).
//
// The queue is built by some fifty builders, each reading its own records.
// Go has the builders a field officer's queue runs (see Handled). A reader
// is answered only when every builder their role reaches is one of them, and
// none of the guarded ones has anything to say; anyone else is passed to the
// existing application. Which builders a role reaches is exported from the
// queue itself, so a builder added there makes Go pass the role on.
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_todos_rules`;
// apps/command_center/test_todos_rules_export.py fails when the two differ.
package todos

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given: the page, and the builders its queue runs.
type Role struct {
	Page     bool     `json:"page"`
	Builders []string `json:"builders"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles             map[string]Role            `json:"roles"`
	Builders          []string                   `json:"builders"`
	PartnerScopeRoles []string                   `json:"partner_scope_roles"`
	OpenLinks         map[string]map[string]bool `json:"open_links"`
	CategoryTones     map[string]string          `json:"category_tones"`
	PriorityOrder     map[string]int             `json:"priority_order"`
	PriorityLabel     map[string]string          `json:"priority_label"`
	Actionable        []string                   `json:"actionable"`
	Waiting           []string                   `json:"waiting"`
	ActionMeta        map[string][2]string       `json:"action_meta"`
	GroupMin          int                        `json:"group_min"`

	ActivityTypeLabels          map[string]string   `json:"activity_type_labels"`
	ActivityFieldChoices        map[string][]string `json:"activity_field_choices"`
	ActivitySettledStatuses     []string            `json:"activity_settled_statuses"`
	WeeklyConfirmStatus         string              `json:"weekly_confirm_status"`
	WeeklyReturnedStatuses      []string            `json:"weekly_returned_statuses"`
	WeeklyApproverStatus        map[string]string   `json:"weekly_approver_status"`
	MonthlyReturnedStatuses     []string            `json:"monthly_returned_statuses"`
	PartnerDelaySettledStatuses []string            `json:"partner_delay_settled_statuses"`
	ReturnedToStaffStatus       string              `json:"returned_to_staff_status"`
	TeamActionActiveStates      []string            `json:"team_action_active_states"`
	VisitRequestAwaiting        string              `json:"visit_request_awaiting"`
	CoreDoneStatuses            []string            `json:"core_done_statuses"`
	CoreInFlightStatuses        []string            `json:"core_in_flight_statuses"`
	CoreReturnedStatuses        []string            `json:"core_returned_statuses"`
	CoreKinds                   [][2]string         `json:"core_kinds"`
	LoanFieldVerificationStates []string            `json:"loan_field_verification_statuses"`
	OperatingStatuses           []string            `json:"operating_statuses"`
	ExtraOpenStatuses           []string            `json:"extra_open_statuses"`
	ProjectNotYetMeasurable     string              `json:"project_not_yet_measurable"`
	EvidenceTables              []string            `json:"evidence_tables"`
	EvidenceReturned            string              `json:"evidence_returned"`
	OnetestDeliveredStatuses    []string            `json:"onetest_delivered_statuses"`
	ClusterSessionTypes         []string            `json:"cluster_session_types"`
	ClusterDeliveredStatuses    []string            `json:"cluster_delivered_statuses"`
	MissedInARowAlert           int                 `json:"missed_in_a_row_alert"`
	AttendanceMaxRows           int                 `json:"attendance_max_rows"`
	PlanningCountry             string              `json:"planning_country"`
	TargetReviewType            string              `json:"target_review_type"`
	TargetReviewStagesNotAgreed []string            `json:"target_review_stages_not_agreed"`

	Lead LeadRules `json:"lead"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || len(r.Builders) == 0 ||
		len(r.OpenLinks) == 0 || len(r.PriorityOrder) == 0 || len(r.ActionMeta) == 0 || r.GroupMin <= 0 ||
		len(r.ActivityTypeLabels) == 0 || len(r.CoreKinds) == 0 || r.MissedInARowAlert <= 0 ||
		r.AttendanceMaxRows <= 0 || r.Lead.OneToOneDueDay <= 0 || r.Lead.CoachingRowLimit <= 0 || r.Lead.SSAPendingStatus == "" || r.PlanningCountry == "" || len(r.EvidenceTables) == 0 {
		panic(fmt.Sprintf("todos: the embedded rules are unreadable: %v", err))
	}
	return r
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// typeLabel is get_activity_type_display(): the choice's label, or the value
// itself when it is not a choice.
func typeLabel(t string) string {
	if label, ok := rules.ActivityTypeLabels[t]; ok {
		return label
	}
	return t
}
