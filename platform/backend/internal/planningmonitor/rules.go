// Package planningmonitor is the Planning Monitor
// (apps.planning.planning_monitor and the figures apps.planning.readiness
// folds from it): each Programme Lead's and CCEO's year against the 280 or
// 560 visits their role plans, the Partner's share, training coverage, the
// schools nobody has planned for, and every planned activity and where it is
// counted. Every figure is folded from the school rows under it, so a team's
// total is the sum of its people's.
//
// It reads; it never writes. The vocabularies are exported to rules.json by
// `manage.py export_planning_monitor_rules`;
// apps/planning/test_planning_monitor_rules_export.py fails when the two
// differ.
package planningmonitor

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// requirement is one school type's year (rules.TypeRequirement).
type requirement struct {
	StaffVisits      int `json:"staff_visits"`
	PartnerVisits    int `json:"partner_visits"`
	EitherVisits     int `json:"either_visits"`
	StaffTrainings   int `json:"staff_trainings"`
	PartnerTrainings int `json:"partner_trainings"`
	EitherTrainings  int `json:"either_trainings"`
}

func (r requirement) visits() int { return r.StaffVisits + r.PartnerVisits + r.EitherVisits }
func (r requirement) trainings() int {
	return r.StaffTrainings + r.PartnerTrainings + r.EitherTrainings
}

var rules = func() (r struct {
	RulesVersion                string                 `json:"rules_version"`
	ProgramLeadRole             string                 `json:"program_lead_role"`
	CCEORole                    string                 `json:"cceo_role"`
	RoleCodes                   map[string]string      `json:"role_codes"`
	VisitTargets                map[string]int         `json:"visit_targets"`
	RoleLabels                  map[string]string      `json:"role_labels"`
	NoLead                      [2]string              `json:"no_lead"`
	Unassigned                  [2]string              `json:"unassigned"`
	CoreTypes                   []string               `json:"core_types"`
	ClientTypes                 []string               `json:"client_types"`
	CoreStaffVisits             int                    `json:"core_staff_visits"`
	CorePartner                 int                    `json:"core_partner"`
	TypeOrder                   []string               `json:"type_order"`
	TypeLabels                  map[string]string      `json:"type_labels"`
	Requirements                map[string]requirement `json:"requirements"`
	TrainedTypes                []string               `json:"trained_types"`
	VisitShapeTypes             []string               `json:"visit_shape_types"`
	CompanionPurpose            string                 `json:"companion_purpose"`
	OutreachPurposes            []string               `json:"outreach_purposes"`
	OutreachTypes               []string               `json:"outreach_types"`
	DataCollectionPurposes      []string               `json:"data_collection_purposes"`
	DataCollectionTypes         []string               `json:"data_collection_types"`
	PurposeKinds                map[string]string      `json:"purpose_kinds"`
	TypeKinds                   map[string]string      `json:"type_kinds"`
	KindSSA                     string                 `json:"kind_ssa"`
	PlannedStates               []string               `json:"planned_states"`
	AssignedToPartner           string                 `json:"assigned_to_partner"`
	DatedByPartner              string                 `json:"dated_by_partner"`
	CertifiedPartnerAgency      string                 `json:"certified_partner_agency"`
	DeliveredStatuses           []string               `json:"delivered_statuses"`
	OfficerCompletedStatuses    []string               `json:"officer_completed_statuses"`
	UnscheduledHandoverStatuses []string               `json:"unscheduled_handover_statuses"`
	SchoolTrainingTypes         []string               `json:"school_training_types"`
	TrainingTypes               []string               `json:"training_types"`
	ClusterMeetingTypes         []string               `json:"cluster_meeting_types"`
	OpenProjectStatuses         []string               `json:"open_project_statuses"`
	CurrentSSAStatuses          []string               `json:"current_ssa_statuses"`
	OperatingStatuses           []string               `json:"operating_statuses"`
	Gaps                        [][2]string            `json:"gaps"`
	Lists                       [][2]string            `json:"lists"`
	GapColumns                  [][3]string            `json:"gap_columns"`
	GapFigures                  map[string]string      `json:"gap_figures"`
	Ledger                      [][3]any               `json:"ledger"`
	PillarLabels                map[string]string      `json:"pillar_labels"`
	KPILabels                   map[string]string      `json:"kpi_labels"`
	MonitorTabs                 [][2]string            `json:"monitor_tabs"`
	// Page is /planning-monitor/ on its own: who opens it, who reads it as
	// the country, the role it sends to the dashboard and those it sends to
	// Planning Oversight.
	Page struct {
		Roles          []string `json:"roles"`
		CountryRoles   []string `json:"country_roles"`
		DashboardRole  string   `json:"dashboard_role"`
		OversightRoles []string `json:"oversight_roles"`
		OversightPath  string   `json:"oversight_path"`
		// CountryLensRoles read the whole country (resolve_oversight_scope);
		// CountryRoles also call it the country's (is_country_reader).
		CountryLensRoles []string `json:"country_lens_roles"`
	} `json:"page"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("planningmonitor: reading rules.json: %v", err))
	}
	if r.CCEORole == "" || len(r.Requirements) == 0 || len(r.VisitShapeTypes) == 0 || len(r.PlannedStates) == 0 ||
		len(r.Ledger) == 0 || r.CoreStaffVisits == 0 {
		panic("planningmonitor: rules.json lacks the roles, the requirements, the visits, the states or the ledger")
	}
	return r
}()

// need is requirement_for: the year a school of the type takes.
func need(schoolType string) requirement { return rules.Requirements[schoolType] }

// takesTraining is rules.takes_training.
func takesTraining(schoolType string) bool { return slices.Contains(rules.TrainedTypes, schoolType) }

func isCore(schoolType string) bool { return slices.Contains(rules.CoreTypes, schoolType) }

func monitored(schoolType string) bool {
	return isCore(schoolType) || slices.Contains(rules.ClientTypes, schoolType)
}

// typeLabel is rules.type_label.
func typeLabel(schoolType string) string {
	if l, ok := rules.TypeLabels[schoolType]; ok && l != "" {
		return l
	}
	if schoolType == "" {
		return "No type"
	}
	return pyTitle(schoolType)
}
