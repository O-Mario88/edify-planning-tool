// Package projectplanning builds the Special Projects Planning
// (/projects/planning): every school a project holds, one block a project,
// with its SSA state, the planning readiness this quarter's project work and
// any partner handover give it, the weakest intervention, the recommended
// action and the partner, beside the year's figures, the readiness bands,
// the chosen school's context and a summary by project
// (apps.frontend.views.extended_views.special_projects_planning_view,
// apps.projects.planning_service.get_planning and
// partials/projects/planning_workspace.html, as the existing feed reads them).
//
// It reads; it never writes. It hands the page on for the queue's file (the
// export query), a query it does not know, and a queue longer than four
// pages (the pager folds its middle pages). The doors and words are exported
// to rules.json by `manage.py export_project_planning_rules`;
// apps/projects/test_project_planning_rules_export.py fails when the two
// differ.
package projectplanning

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

type roleRules struct {
	Page             bool            `json:"page"`
	Strip            json.RawMessage `json:"strip"`
	CanSchedule      bool            `json:"can_schedule"`
	CanAssignPartner bool            `json:"can_assign_partner"`
	CanExport        bool            `json:"can_export"`
	SchoolLinks      bool            `json:"school_links"`
}

var rules = func() (r struct {
	Roles                       map[string]roleRules `json:"roles"`
	MetricLabels                []string             `json:"metric_labels"`
	ActivityTypes               map[string]string    `json:"activity_types"`
	Statuses                    map[string]string    `json:"statuses"`
	StaffVerificationStatuses   map[string]string    `json:"staff_verification_statuses"`
	SchoolTypes                 map[string]string    `json:"school_types"`
	Interventions               map[string]string    `json:"interventions"`
	ProjectTypes                map[string]string    `json:"project_types"`
	ActiveStatuses              []string             `json:"active_statuses"`
	ReturnedStatuses            []string             `json:"returned_statuses"`
	LivePlanStatuses            []string             `json:"live_plan_statuses"`
	OperatingSchoolStatuses     []string             `json:"operating_school_statuses"`
	UnscheduledHandoverStatuses []string             `json:"unscheduled_handover_statuses"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("projectplanning: reading rules.json: %v", err))
	}
	if len(r.MetricLabels) != 9 || len(r.Roles) == 0 || len(r.OperatingSchoolStatuses) == 0 {
		panic("projectplanning: rules.json lacks the figures' labels, the doors or the school statuses")
	}
	return r
}()

func in(set []string, v string) bool { return slices.Contains(set, v) }

func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}

// The statuses _activity_state reads as done and as handed in.
var (
	doneStatuses     = []string{"completed", "ia_verified", "accountant_confirmed", "closed"}
	handedInStatuses = []string{"awaiting_ia_verification", "submitted_to_pl", "evidence_uploaded"}
	notPlanned       = []string{"cancelled", "rejected", "deferred"}
	tabs             = []string{"all", "baseline", "ready", "partner", "scheduled"}
	sizes            = []int{10, 25, 50}
)
