// Package coreschools builds Core Schools Planning (/core-schools:
// apps.frontend.views.core_schools_views.core_schools_view, as the existing
// feed reads pages/core_schools/index.html with its three lazily drawn tabs):
// the reader's core schools for a year with each one's package of four
// visits and four trainings, the planning queue, the intervention impact,
// the staff and partner outcomes, the right-hand guidance and the
// programme (Core Trained, Core Graduate, Champion) tables.
//
// It reads; it never writes. The existing page gives every core school in
// the reader's scope its package for the year on each read
// (CoreSchoolsService.self_heal_plans and carry_packages_forward); Go hands
// that read on whenever the heal would write anything. It also hands on the
// read-only Team Core Oversight lens and any query it does not read. The
// doors, sizes, names and states are exported to rules.json by `manage.py
// export_core_schools_rules`; apps/core_schools/test_core_schools_rules_export.py
// fails when the two differ.
package coreschools

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// door is what a role is given on the page.
type door struct {
	AssignPartner bool `json:"assign_partner"`
	BulkSchedule  bool `json:"bulk_schedule"`
	AssignProject bool `json:"assign_project"`
	OpenClusters  bool `json:"open_clusters"`
	OpenOversight bool `json:"open_oversight"`
}

// tick is whether the reader's list carries tick boxes (the direct lens).
func (d door) tick() bool { return d.AssignPartner || d.BulkSchedule || d.AssignProject }

var rules = func() (r struct {
	Roles                  map[string]door   `json:"roles"`
	PageSizes              []int             `json:"page_sizes"`
	PageSizeDefault        int               `json:"page_size_default"`
	Interventions          [][2]string       `json:"interventions"`
	SchoolTypes            [][2]string       `json:"school_types"`
	ProgrammeTypes         [][2]string       `json:"programme_types"`
	ProgrammeSchoolTypes   []string          `json:"programme_school_types"`
	OutreachOnlyTypes      []string          `json:"outreach_only_types"`
	AssessmentRank         []string          `json:"assessment_rank"`
	AssessmentWords        map[string]string `json:"assessment_words"`
	AssessmentMissing      string            `json:"assessment_missing"`
	PartnerReturnedToStaff string            `json:"partner_returned_to_staff"`
	PartnerReleased        []string          `json:"partner_released"`
	PartnerUnscheduled     []string          `json:"partner_unscheduled"`
	SlotDoneWithLegacy     []string          `json:"slot_done_with_legacy"`
	PlanClosedStatuses     []string          `json:"plan_closed_statuses"`
	RecommendationDone     []string          `json:"recommendation_done"`
	ImpactActive           []string          `json:"impact_active"`
	ImpactCompleted        []string          `json:"impact_completed"`
	WorkExcluded           []string          `json:"work_excluded"`
	ClusterTrainingTypes   []string          `json:"cluster_training_types"`
	SessionLiveStatuses    []string          `json:"session_live_statuses"`
	VisitTypes             []string          `json:"visit_types"`
	TrainingTypes          []string          `json:"training_types"`
	ActivityTypeLabels     map[string]string `json:"activity_type_labels"`
	ActivityStatusLabels   map[string]string `json:"activity_status_labels"`
	SlotOrdinals           map[string]string `json:"slot_ordinals"`
	CountrySchedulingRoles []string          `json:"country_scheduling_roles"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.PageSizes) == 0 ||
		len(r.Interventions) == 0 || len(r.ProgrammeTypes) == 0 || len(r.SlotOrdinals) != 4 {
		panic(fmt.Sprintf("coreschools: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// interventionLabel is SsaIntervention's name for a code, or the code.
func interventionLabel(code string) string {
	for _, c := range rules.Interventions {
		if c[0] == code {
			return c[1]
		}
	}
	return code
}

// schoolTypeLabel is get_school_type_display.
func schoolTypeLabel(value string) string {
	for _, c := range rules.SchoolTypes {
		if c[0] == value {
			return c[1]
		}
	}
	return value
}
