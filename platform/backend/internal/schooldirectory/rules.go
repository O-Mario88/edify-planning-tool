// Package schooldirectory is the School Directory, owned by Go (owner brief,
// 2026-11-11: "School Directory and School Profiles"): the schools a person
// may see, with the same filters, counts, order, row facts and row actions
// as the existing page (apps.frontend.views.school_views
// .school_directory_context and the app's feed of it,
// apps.mobile_feed.views.SchoolDirectoryFeedView).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_school_directory_rules`;
// apps/schools/test_school_directory_rules_export.py fails when the two
// differ.
package schooldirectory

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Rules are the directory's vocabularies.
type Rules struct {
	PageAccess map[string]struct {
		Directory bool `json:"directory"`
		Profile   bool `json:"profile"`
	} `json:"page_access"`
	CountryRoles            []string          `json:"country_roles"`
	RegionRoles             []string          `json:"region_roles"`
	SummaryOnlyRoles        []string          `json:"summary_only_roles"`
	TakeRoles               []string          `json:"take_roles"`
	CapacityExemptRoles     []string          `json:"capacity_exempt_roles"`
	AllowCDOperational      bool              `json:"allow_cd_operational_planning"`
	SchoolTypes             [][2]string       `json:"school_types"`
	TrainedTypes            []string          `json:"trained_types"`
	VisitTypes              []string          `json:"visit_types"`
	VisitCountTypes         []string          `json:"visit_count_types"`
	ClusterSessionTypes     []string          `json:"cluster_session_types"`
	ClusterMeetingTypes     []string          `json:"cluster_meeting_types"`
	SchoolTrainingTypes     []string          `json:"school_training_types"`
	ClusterTrainingTypes    []string          `json:"cluster_training_types"`
	CompletedWorkStatuses   []string          `json:"completed_work_statuses"`
	ClusterCreditStatuses   []string          `json:"cluster_credit_statuses"`
	CurrentSSAStatuses      []string          `json:"current_ssa_statuses"`
	DeadStatuses            []string          `json:"dead_statuses"`
	PendingApprovalStatuses []string          `json:"pending_approval_statuses"`
	VisitStatusStates       map[string]string `json:"visit_status_states"`
	VisitPrecedence         []string          `json:"visit_precedence"`
	VisitLabels             map[string]string `json:"visit_labels"`
	VisitTones              map[string]string `json:"visit_tones"`
	SSAInterventions        [][2]string       `json:"ssa_interventions"`
	SSAGroups               [][3]string       `json:"ssa_groups"`
	GapLabels               [][2]string       `json:"gap_labels"`
	OpenProjectStatuses     []string          `json:"open_project_statuses"`
	DirectoryTabs           [][2]string       `json:"directory_tabs"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.DirectoryTabs) == 0 || len(r.VisitPrecedence) == 0 {
		panic(fmt.Sprintf("schooldirectory: the embedded rules are unreadable: %v", err))
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// schoolTypeLabel is School.get_school_type_display: the choice's label, or
// the stored value itself when it names no choice.
func schoolTypeLabel(value string) string {
	for _, choice := range rules.SchoolTypes {
		if choice[0] == value {
			return choice[1]
		}
	}
	return value
}

// gapLabel is data_gaps.LABELS[key], and whether key names a gap.
func gapLabel(key string) (string, bool) {
	for _, gap := range rules.GapLabels {
		if gap[0] == key {
			return gap[1], true
		}
	}
	return "", false
}
