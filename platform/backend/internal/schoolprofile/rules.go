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
	MyPlan        bool `json:"my_plan"`
	CoreSchools   bool `json:"core_schools"`
	BTSensitive   bool `json:"bt_sensitive"`
	BTManage      bool `json:"bt_manage"`
}

type profileRules struct {
	Doors               map[string]doors   `json:"doors"`
	SchoolTypes         map[string]string  `json:"school_types"`
	Readiness           map[string]string  `json:"readiness"`
	SSAStatuses         map[string]string  `json:"ssa_statuses"`
	SSAInterventions    map[string]string  `json:"ssa_interventions"`
	SSAHoldingStatuses  []string           `json:"ssa_holding_statuses"`
	SSACurrentStatuses  []string           `json:"ssa_current_statuses"`
	SSASources          map[string]string  `json:"ssa_sources"`
	SSASourceStaffKeyed string             `json:"ssa_source_staff_keyed"`
	SSASourceOnVisit    string             `json:"ssa_source_on_visit"`
	SSASourceOther      string             `json:"ssa_source_other"`
	CoreLifecycleTypes  []string           `json:"core_lifecycle_types"`
	ClosedStatuses      []string           `json:"closed_statuses"`
	ClosedSchoolMessage string             `json:"closed_school_message"`
	OperationalStatuses map[string]string  `json:"operational_statuses"`
	ClosureReasons      map[string]string  `json:"closure_reasons"`
	Gate                visitgate.Rules    `json:"gate"`
	Engine              engineRules        `json:"engine"`
	Participation       participationRules `json:"participation"`
	CoreTab             coreTabRules       `json:"core_tab"`
	BT                  btRules            `json:"business_transformation"`
}

// btRules are what the Business Transformation panel and the loans strip
// read (export "business_transformation").
type btRules struct {
	UgandaWideRoles         []string          `json:"uganda_wide_roles"`
	MFIRoles                []string          `json:"mfi_roles"`
	ImpactCountryRoles      []string          `json:"impact_country_roles"`
	ImpactCountryBoundRoles []string          `json:"impact_country_bound_roles"`
	OpenCaseStatuses        []string          `json:"open_case_statuses"`
	FundedLoanStatuses      []string          `json:"funded_loan_statuses"`
	CaseStatuses            map[string]string `json:"case_statuses"`
	RecommendationKinds     map[string]string `json:"recommendation_kinds"`
	LoanStatuses            map[string]string `json:"loan_statuses"`
	SalesforceStatuses      map[string]string `json:"salesforce_statuses"`
	ImpactStatuses          map[string]string `json:"impact_statuses"`
	RequirementStatuses     map[string]string `json:"requirement_statuses"`
	ValidationStatuses      map[string]string `json:"validation_statuses"`
	ComplianceStatuses      map[string]string `json:"compliance_statuses"`
}

// coreTabRules are what the Core School tab reads (export "core_tab").
type coreTabRules struct {
	TrajectoryLabels map[string]string `json:"trajectory_labels"`
	Champion         struct {
		Champion       string   `json:"champion"`
		Potential      string   `json:"potential"`
		Progressing    string   `json:"progressing"`
		NotYet         string   `json:"not_yet"`
		Insufficient   string   `json:"insufficient"`
		LatestAvg      float64  `json:"latest_avg"`
		StoredChampion []string `json:"stored_champion"`
	} `json:"champion"`
	SlotDoneStatuses          []string          `json:"slot_done_statuses"`
	PackageWorkKinds          []string          `json:"package_work_kinds"`
	PackageWorkSlots          int               `json:"package_work_slots"`
	HandoverUnscheduled       []string          `json:"handover_unscheduled"`
	HandoverScheduled         []string          `json:"handover_scheduled"`
	HandoverCompleted         string            `json:"handover_completed"`
	DeliveredStatuses         []string          `json:"delivered_statuses"`
	ClusterSessionTypes       []string          `json:"cluster_session_types"`
	TrainingTypes             []string          `json:"training_types"`
	CountryWriteRoles         []string          `json:"country_write_roles"`
	RecommendationStates      map[string]string `json:"recommendation_states"`
	RecommendationLiveStates  []string          `json:"recommendation_live_states"`
	RecommendationShownStates []string          `json:"recommendation_shown_states"`
}

// participationRules are what the Participation tab reads: the activity
// list's statuses and words, who may run work, and a hand-over's next step.
type participationRules struct {
	OpenStatuses                    []string          `json:"open_statuses"`
	DeliveredStatuses               []string          `json:"delivered_statuses"`
	PlannedStatuses                 []string          `json:"planned_statuses"`
	NeedsReplanningStatuses         []string          `json:"needs_replanning_statuses"`
	VerifiedStatuses                []string          `json:"verified_statuses"`
	StillCompletingStatuses         []string          `json:"still_completing_statuses"`
	EditableStatuses                []string          `json:"editable_statuses"`
	BegunStatuses                   []string          `json:"begun_statuses"`
	ExecutedStatuses                []string          `json:"executed_statuses"`
	PageSize                        int               `json:"page_size"`
	ActivityTypes                   map[string]string `json:"activity_types"`
	MeetingKinds                    map[string]string `json:"meeting_kinds"`
	CountrySchedulingRoles          []string          `json:"country_scheduling_roles"`
	CountryDirector                 string            `json:"country_director"`
	HandoverLeftStatuses            []string          `json:"handover_left_statuses"`
	HandoverReturnedStatus          string            `json:"handover_returned_status"`
	HandoverUnscheduledStatuses     []string          `json:"handover_unscheduled_statuses"`
	OversightCompleteStatuses       []string          `json:"oversight_complete_statuses"`
	OversightAwaitingIAStatuses     []string          `json:"oversight_awaiting_ia_statuses"`
	OversightEvidenceReviewStatuses []string          `json:"oversight_evidence_review_statuses"`
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
	Scope scopeRules `json:"scope"`
}

// scopeRules are what a profile of many schools reads (export "scope"):
// the operating schools, each kind's sections and levels, the rankings'
// sentences and the Schools tab's lists.
type scopeRules struct {
	OperatingStatuses []string            `json:"operating_statuses"`
	Sections          [][2]string         `json:"sections"`
	SectionsOf        map[string][]string `json:"sections_of"`
	TeamLabel         string              `json:"team_label"`
	LevelsOf          map[string][]string `json:"levels_of"`
	LevelLabels       map[string]string   `json:"level_labels"`
	PeriodOptions     [][2]string         `json:"period_options"`
	ShowLabels        map[string]string   `json:"show_labels"`
	ShowOrder         []string            `json:"show_order"`
	Ranked            int                 `json:"ranked"`
	RankingMethod     string              `json:"ranking_method"`
	MoversMethod      string              `json:"movers_method"`
	SchoolTypeOrder   []string            `json:"school_type_order"`
	OnlineMode        string              `json:"online_mode"`
	FYChoices         int                 `json:"fy_choices"`
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
