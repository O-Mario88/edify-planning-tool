// Package planningpage is the Planning page (/planning), owned by Go (owner
// brief, 2026-11-11: "Activity planning and scheduling"): the schools a
// person plans for, with the same filters, strip, workload line, tabs,
// rows, doors and pages as the existing page
// (apps.frontend.views.planning_views.planning_dashboard_view,
// apps.planning.planning_service.PlanningDashboardService.get_dashboard_data
// and the page's templates), as the app's feed reads it (apps.mobile_feed).
//
// Its Client Schools and Core Schools tabs are Go's; the Clusters, Assigned
// to Partner and Scheduled / In My Plan tabs, and a page opened from a
// priority allocation, are still answered by the existing application.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_planning_page_rules`;
// apps/planning/test_planning_page_rules_export.py fails when they differ.
package planningpage

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Doors is what a role may do on the page.
type Doors struct {
	Page          bool `json:"page"`
	Schedule      bool `json:"schedule"`
	AssignPartner bool `json:"assign_partner"`
	BulkSchedule  bool `json:"bulk_schedule"`
	OpenSchool    bool `json:"open_school"`
}

// CountedVisits are the rules a person's counted visits are read by
// (staff_plan.counted_visits) and the targets of the planning roles.
type CountedVisits struct {
	VisitShapeTypes        []string       `json:"visit_shape_types"`
	CompanionPurpose       string         `json:"companion_purpose"`
	OutreachPurposes       []string       `json:"outreach_purposes"`
	DataCollectionPurposes []string       `json:"data_collection_purposes"`
	DataCollectionTypes    []string       `json:"data_collection_types"`
	KindPurposes           []string       `json:"kind_purposes"`
	PlannedStates          []string       `json:"planned_states"`
	ProgramLeadRole        string         `json:"program_lead_role"`
	CCEORole               string         `json:"cceo_role"`
	VisitTargets           map[string]int `json:"visit_targets"`
	CoreTypes              []string       `json:"core_types"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Doors                     map[string]Doors `json:"doors"`
	ClientTabTypes            []string         `json:"client_tab_types"`
	PartnerPendingStatuses    []string         `json:"partner_pending_statuses"`
	PartnerLiveStatuses       []string         `json:"partner_live_statuses"`
	NotActiveWorkStatuses     []string         `json:"not_active_work_statuses"`
	RowVisitCountTypes        []string         `json:"row_visit_count_types"`
	RowTrainingCountTypes     []string         `json:"row_training_count_types"`
	RowAttendanceTypes        []string         `json:"row_attendance_types"`
	LivePlanStatuses          []string         `json:"live_plan_statuses"`
	NotScheduledStatuses      []string         `json:"not_scheduled_statuses"`
	NotInThePlan              []string         `json:"not_in_the_plan"`
	NotInPlanActivityStatuses []string         `json:"not_in_plan_activity_statuses"`
	CompletedWorkStatuses     []string         `json:"completed_work_statuses"`
	InformedAlignments        []string         `json:"informed_alignments"`
	OwnTableSchoolTypes       []string         `json:"own_table_school_types"`
	ReadinessChoices          [][2]string      `json:"readiness_choices"`
	SSAStatusChoices          [][2]string      `json:"ssa_status_choices"`
	SupportFilters            [][2]string      `json:"support_filters"`
	StripLabels               []string         `json:"strip_labels"`
	CountedVisits             CountedVisits    `json:"counted_visits"`
	Catalogue                 struct {
		Country string `json:"country"`
		Kind    string `json:"kind"`
		Status  string `json:"status"`
	} `json:"catalogue"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Doors) == 0 || len(r.StripLabels) != 9 || len(r.SupportFilters) == 0 {
		panic(fmt.Sprintf("planningpage: the embedded rules are unreadable: %v", err))
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }
