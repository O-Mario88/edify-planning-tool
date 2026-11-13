// Package clusterpage is the Clusters page (/clusters), owned by Go (owner
// brief, 2026-11-11: "District and Cluster management"): the clusters a
// person plans in, with the same filters, strip, cards, doors and pages as
// the existing page (apps.frontend.views.cluster_views.cluster_list_view,
// apps.clusters.services.ClusterDashboardService.get_dashboard_data and the
// page's templates), as the app's feed reads it (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_cluster_page_rules`;
// apps/clusters/test_cluster_page_rules_export.py fails when the two differ.
package clusterpage

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Doors is what a role may do on the page, by the page's own gates.
type Doors struct {
	Page       bool `json:"page"`
	Plan       bool `json:"plan"`
	Create     bool `json:"create"`
	AddSchools bool `json:"add_schools"`
	// A card's schools (cluster_schools_partial) and its rows' doors.
	SchoolsList   bool `json:"schools_list"`
	Schedule      bool `json:"schedule"`
	AssignPartner bool `json:"assign_partner"`
	BulkSchedule  bool `json:"bulk_schedule"`
	OpenSchool    bool `json:"open_school"`
}

// SupportRule is support_responsibility.visibility_enabled's settings.
type SupportRule struct {
	Enabled    bool     `json:"enabled"`
	PilotRoles []string `json:"pilot_roles"`
	PilotUsers []string `json:"pilot_users"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Doors                       map[string]Doors `json:"doors"`
	OperatingStatuses           []string         `json:"operating_statuses"`
	OwnTableSchoolTypes         []string         `json:"own_table_school_types"`
	CompletedWorkStatuses       []string         `json:"completed_work_statuses"`
	CardTrainingTypes           []string         `json:"card_training_types"`
	PlanningDoneStatuses        []string         `json:"planning_done_statuses"`
	PlanningOpenStatuses        []string         `json:"planning_open_statuses"`
	PlanningTrainingTypes       []string         `json:"planning_training_types"`
	PlanningSchoolTrainingTypes []string         `json:"planning_school_training_types"`
	SSAInterventions            [][2]string      `json:"ssa_interventions"`
	StripLabels                 []string         `json:"strip_labels"`
	SupportRule                 SupportRule      `json:"support_rule"`
	VisitTypes                  []string         `json:"visit_types"`
	TrainingTypes               []string         `json:"training_types"`
	NotPassedQueryKeys          []string         `json:"not_passed_query_keys"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Doors) == 0 || len(r.StripLabels) != 8 || len(r.SSAInterventions) == 0 || len(r.NotPassedQueryKeys) == 0 {
		panic(fmt.Sprintf("clusterpage: the embedded rules are unreadable: %v", err))
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// interventionLabel is SsaIntervention(value).label.
func interventionLabel(value string) string {
	for _, iv := range rules.SSAInterventions {
		if iv[0] == value {
			return iv[1]
		}
	}
	return value
}
