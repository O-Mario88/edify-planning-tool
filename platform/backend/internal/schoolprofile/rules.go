// Package schoolprofile builds a school's profile (School 360) in Go, a
// port of the existing school_detail_view and the page blocks the mobile
// feed reads from it (apps.mobile_feed.page_blocks), so the app is answered
// with the same header, tabs and panels.
//
// It answers the Details tab of an open school that is not Core and has no
// Business Transformation case or MFI loan, for someone working in their own
// role. Everything else — the engine's tabs, Core and closed schools, the
// loan register, an acting capacity — is still the existing application's,
// and Build says so (served is false) so the gateway passes it on.
package schoolprofile

import (
	_ "embed"
	"encoding/json"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

//go:embed rules.json
var rulesJSON []byte

// doors are what one role may do from a school's profile, as the existing
// gates answer (manage.py export_school_profile_rules).
type doors struct {
	Profile       bool `json:"profile"`
	Schedule      bool `json:"schedule"`
	AssignPartner bool `json:"assign_partner"`
	TransferOwner bool `json:"transfer_owner"`
	AssignProject bool `json:"assign_project"`
	EnterSSA      bool `json:"enter_ssa"`
	DeleteSchool  bool `json:"delete_school"`
	Take          bool `json:"take"`
	OpenCluster   bool `json:"open_cluster"`
	OpenDistrict  bool `json:"open_district"`
	OpenStaff     bool `json:"open_staff"`
	OpenProjects  bool `json:"open_projects"`
	Loans         bool `json:"loans"`
}

type profileRules struct {
	Doors               map[string]doors  `json:"doors"`
	SchoolTypes         map[string]string `json:"school_types"`
	Readiness           map[string]string `json:"readiness"`
	SSAStatuses         map[string]string `json:"ssa_statuses"`
	SSAInterventions    map[string]string `json:"ssa_interventions"`
	SSAHoldingStatuses  []string          `json:"ssa_holding_statuses"`
	SSACurrentStatuses  []string          `json:"ssa_current_statuses"`
	SSASources          map[string]string `json:"ssa_sources"`
	SSASourceStaffKeyed string            `json:"ssa_source_staff_keyed"`
	SSASourceOnVisit    string            `json:"ssa_source_on_visit"`
	SSASourceOther      string            `json:"ssa_source_other"`
	CoreLifecycleTypes  []string          `json:"core_lifecycle_types"`
	ClosedStatuses      []string          `json:"closed_statuses"`
	ClosedSchoolMessage string            `json:"closed_school_message"`
	Gate                visitgate.Rules   `json:"gate"`
	Engine              engineRules       `json:"engine"`
}

// engineRules are the profile engine's vocabularies.
type engineRules struct {
	CompletedWorkStatuses    []string          `json:"completed_work_statuses"`
	NotInPlanStatuses        []string          `json:"not_in_plan_statuses"`
	NotStartedStatuses       []string          `json:"not_started_statuses"`
	ChangeLabels             map[string]string `json:"change_labels"`
	ChangeTones              map[string]string `json:"change_tones"`
	StrongScore              float64           `json:"strong_score"`
	HandoverReleasedStatuses []string          `json:"handover_released_statuses"`
	HandoverCompletedStatus  string            `json:"handover_completed_status"`
	StoryStatuses            struct {
		Draft    string   `json:"draft"`
		Approved string   `json:"approved"`
		Waiting  []string `json:"waiting"`
	} `json:"story_statuses"`
	InterventionAbbreviations map[string]string `json:"intervention_abbreviations"`
	InterventionOrder         []string          `json:"intervention_order"`
	HelperFigureChars         int               `json:"helper_figure_chars"`
	VisitTypes                []string          `json:"visit_types"`
	TrainingTypes             []string          `json:"training_types"`
	MeetingTypes              []string          `json:"meeting_types"`
	InterventionMethod        string            `json:"intervention_method"`
	SSATarget                 float64           `json:"ssa_target"`
	RuleSentence              string            `json:"rule_sentence"`
	StateTones                map[string]string `json:"state_tones"`
	VerifiedActivityStatuses  []string          `json:"verified_activity_statuses"`
	SchoolPairsShown          int               `json:"school_pairs_shown"`
	MinIntervalDays           int               `json:"min_interval_days"`
	FallbackRuleLabel         string            `json:"fallback_rule_label"`
	Requirements              map[string]struct {
		Visits    int  `json:"visits"`
		Trainings int  `json:"trainings"`
		TakesSSA  bool `json:"takes_ssa"`
	} `json:"requirements"`
}

var rules = mustLoad()

func mustLoad() profileRules {
	var r profileRules
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("schoolprofile: rules.json: %v", err))
	}
	for value := range r.SSAInterventions {
		r.Gate.SSAInterventions = append(r.Gate.SSAInterventions, value)
	}
	r.Gate.SchoolTypeLabels = r.SchoolTypes
	return r
}

// label is a Django choice's display: its label, or the stored value where
// the choice is not on the list (get_FOO_display).
func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}
