// Package partneroversight is Partner Monitoring (/partner-oversight/): one
// Partner at a time, the schools, clusters and activities handed to it, by
// team member, and where each stands, as the existing page draws it
// (apps.frontend.views.oversight_views.partner_oversight_view,
// apps.planning.partner_oversight_service, pages/oversight/
// partner_oversight.html with partials/oversight/partner_workspace.html) and
// the app's feed reads it (apps.mobile_feed).
//
// It answers a field officer or a Programme Lead in their own seat (the
// team lens), and the country's and a region's readers one Programme Lead's
// team at a time (leads.go): with no partner work, the page as it opens (page.go); with
// partner work (work.go, build.go, workpage.go), the Partner tabs with their
// follow-up recommendations, the team-member tabs, the headline tiles with
// the Planning Monitor's Partner target, and the open tab's table of the
// chosen Partner's work. What work.go names (a facilitated training waiting
// for its Programme Lead, Special Project work, withdrawal requests, a
// table past one page, recorded engagements, a Partner's contact line on
// the Clusters tab, Core schools the Partner has not dated or whose form is
// in, custom periods) is passed to the existing application
// (served=false).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_partner_oversight_rules`;
// apps/planning/test_partner_oversight_rules_export.py fails when the two
// differ.
package partneroversight

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	// Page opens Partner Monitoring at all.
	Page bool `json:"page"`
	// Lens is how the page reads partner work for the role: "team",
	// "country" or "region" (partner_oversight_service._resolve_scope).
	Lens string `json:"lens"`
	// OwnWorkOnly is a CCEO: their team is their own work alone.
	OwnWorkOnly bool `json:"own_work_only"`
	// CreatePartner offers Add Partner Organisation.
	CreatePartner bool `json:"create_partner"`
	// EngagementRegister shows the partnership register under the work.
	EngagementRegister bool `json:"engagement_register"`
	// RecordsEngagements may record one (the register's empty state says so).
	RecordsEngagements bool `json:"records_engagements"`
	// ReadsOwnEngagements reads only the engagements they recorded.
	ReadsOwnEngagements bool `json:"reads_own_engagements"`
	// ObservationsTile adds the Regional Lead observations tile.
	ObservationsTile bool `json:"observations_tile"`
	// SchoolProfiles and ClusterProfiles link a row's school and cluster
	// names to their profiles.
	SchoolProfiles  bool `json:"school_profiles"`
	ClusterProfiles bool `json:"cluster_profiles"`
	// ResolvesReturns is offered Resolve Exception on a hand-back.
	ResolvesReturns bool `json:"resolves_returns"`
	// WithdrawsPartnerWork is offered a Core school's Withdraw school.
	WithdrawsPartnerWork bool `json:"withdraws_partner_work"`
	// VerifiesIA holds Impact Assessment's verification authority.
	VerifiesIA bool `json:"verifies_ia"`
}

// Tile is one headline tile as the feed reads it.
type Tile struct {
	Label  string `json:"label"`
	Value  string `json:"value"`
	Helper string `json:"helper"`
	Note   string `json:"note"`
	Tone   string `json:"tone"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles                        map[string]Role      `json:"roles"`
	StatusFilterKeys             []string             `json:"status_filter_keys"`
	WorkTabs                     []string             `json:"work_tabs"`
	CoreWorkTab                  string               `json:"core_work_tab"`
	PlanningLeadRole             string               `json:"planning_lead_role"`
	PlanningCCEORole             string               `json:"planning_cceo_role"`
	RosterLeadRole               string               `json:"roster_lead_role"`
	PartnerDelivery              string               `json:"partner_delivery"`
	WithdrawalRequested          string               `json:"withdrawal_requested"`
	LeftPartnerStatuses          []string             `json:"left_partner_statuses"`
	ReturnedToStaff              string               `json:"returned_to_staff"`
	PartnerActionRecommendations []string             `json:"partner_action_recommendations"`
	EngagementMetricWords        map[string][2]string `json:"engagement_metric_words"`
	EngagementAutoloadParams     []string             `json:"engagement_autoload_params"`
	EngagementPageParam          string               `json:"engagement_page_param"`
	ZeroTiles                    []Tile               `json:"zero_tiles"`
	ZeroTilesWithTarget          []Tile               `json:"zero_tiles_with_target"`
	QueryKeysNotPassed           []string             `json:"query_keys_not_passed"`
	Work                         Work                 `json:"work"`
}

// Work are the vocabularies a row of partner work is read with
// (partner_oversight_service, withdrawal_service, completion_columns,
// partner_risk_service).
type Work struct {
	UnscheduledStatuses []string          `json:"unscheduled_statuses"`
	ResolutionLabels    map[string]string `json:"resolution_labels"`
	InProgress          []string          `json:"in_progress"`
	EvidenceReview      []string          `json:"evidence_review"`
	AwaitingIA          []string          `json:"awaiting_ia"`
	Complete            []string          `json:"complete"`
	NotStarted          []string          `json:"not_started"`
	ReturnedToPartner   []string          `json:"returned_to_partner"`
	Paid                []string          `json:"paid"`
	PaymentProcessing   []string          `json:"payment_processing"`
	DataGatheringTypes  []string          `json:"data_gathering_types"`
	DataGatheringLabel  string            `json:"data_gathering_label"`
	Withdrawal          WithdrawalRules   `json:"withdrawal"`
	DatedByStaff        string            `json:"dated_by_staff"`
	SSASupportTypes     []string          `json:"ssa_support_types"`
	VisitTypes          []string          `json:"visit_types"`
	TrainingTypes       []string          `json:"training_types"`
	ClusterMeetingTypes []string          `json:"cluster_meeting_types"`
	PlannedStatuses     []string          `json:"planned_statuses"`
	ActivityTypeLabels  map[string]string `json:"activity_type_labels"`
	InterventionLabels  map[string]string `json:"intervention_labels"`
	PurposeLabels       map[string]string `json:"purpose_labels"`
	Completion          CompletionRules   `json:"completion"`
	FollowUp            FollowUpRules     `json:"follow_up"`
	Risk                RiskRules         `json:"risk"`
}

// FollowUpRules are partners_needing_follow_up's vocabularies: the
// recommendations it keeps, the schools and activities the Country
// Director Analytics read, and the hand-overs that are no longer a
// Partner's school.
type FollowUpRules struct {
	Recommendations   []string `json:"recommendations"`
	OperatingStatuses []string `json:"operating_statuses"`
	NotInPlan         []string `json:"not_in_plan"`
	Completed         []string `json:"completed"`
	Released          []string `json:"released"`
}

// WithdrawalRules are resolve_kind's statuses and action_label's words.
type WithdrawalRules struct {
	NotStarted          []string          `json:"not_started"`
	InProgress          []string          `json:"in_progress"`
	Evidence            []string          `json:"evidence"`
	IACleared           []string          `json:"ia_cleared"`
	Closed              []string          `json:"closed"`
	Paid                []string          `json:"paid"`
	Labels              map[string]string `json:"labels"`
	WithdrawFromPartner string            `json:"withdraw_from_partner"`
}

// CompletionRules are the completion columns' statuses and words.
type CompletionRules struct {
	OfficerCompleted   []string          `json:"officer_completed"`
	CompletedWork      []string          `json:"completed_work"`
	AttendanceTypes    []string          `json:"attendance_types"`
	EvidenceKindLabels map[string]string `json:"evidence_kind_labels"`
	MissingSF          string            `json:"missing_sf"`
	MissingEvidence    string            `json:"missing_evidence"`
	MissingBoth        string            `json:"missing_both"`
}

// RiskRules are partner_risk_service's grace days.
type RiskRules struct {
	ScheduleGraceDays       int `json:"schedule_grace_days"`
	ApproachingDays         int `json:"approaching_days"`
	EvidenceGraceDays       int `json:"evidence_grace_days"`
	ReviewGraceDays         int `json:"review_grace_days"`
	PaymentGraceDays        int `json:"payment_grace_days"`
	IAVerificationGraceDays int `json:"ia_verification_grace_days"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("partneroversight: rules.json: %v", err))
	}
	for _, key := range []string{"recorded", "partners_engaged", "follow_ups_due", "observations"} {
		if _, ok := r.EngagementMetricWords[key]; !ok {
			panic("partneroversight: rules.json lacks the engagement tile " + key)
		}
	}
	if len(r.Work.Complete) == 0 || len(r.Work.Withdrawal.Labels) == 0 || r.Work.Completion.MissingBoth == "" {
		panic("partneroversight: rules.json lacks the work vocabularies")
	}
	if len(r.ZeroTiles) == 0 || len(r.ZeroTiles) != len(r.ZeroTilesWithTarget) || len(r.WorkTabs) == 0 {
		panic("partneroversight: rules.json lacks the tiles or the work tabs")
	}
	return r
}
