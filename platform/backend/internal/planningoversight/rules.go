// Package planningoversight is Planning Oversight (/team-planning-oversight/,
// apps.frontend.views.oversight_views.team_planning_oversight_view) and
// Country Oversight (/country-planning-oversight/,
// country_planning_oversight_view) as the app's feed (apps.mobile_feed)
// opens them, owned by Go piece by piece.
//
// Piece 1 is the pages' doors: every reader either page refuses gets the
// feed's "not available" from Go; every reader it opens for is handed to the
// existing application (served=false) until the lenses are built here.
//
// The doors are the existing ones, exported to rules.json by
// `manage.py export_planning_oversight_rules`;
// apps/planning/test_planning_oversight_rules_export.py fails when the two
// differ.
package planningoversight

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Page is one of the two pages as the feed knows it.
type Page struct {
	// Path is the page's URL as the app opens it.
	Path string `json:"path"`
	// FeedOpensPage: the page's URL name is in the feed's NATIVE_PAGES.
	FeedOpensPage bool `json:"feed_opens_page"`
}

// Door is whether a role reaches one page.
type Door struct {
	// Open: the feed's can_open_url lets the reader open the path.
	Open bool `json:"open"`
	// Page: the view's own page-permission decorator lets the reader in.
	Page bool `json:"page"`
}

// Rules is rules.json.
type Rules struct {
	// Pages by key: "team" and "country".
	Pages map[string]Page `json:"pages"`
	// Doors by role, then by page key.
	Doors map[string]map[string]Door `json:"doors"`
	// TeamPlan is what the Team Plan lens draws for a Programme Lead whose
	// team has nothing planned in the period.
	TeamPlan TeamPlan `json:"team_plan"`
}

// Tab is one tab or link of a strip.
type Tab struct {
	Key    string `json:"key"`
	Label  string `json:"label"`
	Href   string `json:"href"`
	Active bool   `json:"active"`
}

// KPI is one headline tile as _kpi_items builds it over no work.
type KPI struct {
	Label  string `json:"label"`
	Value  string `json:"value"`
	Helper string `json:"helper"`
	Tone   string `json:"tone"`
}

// TeamPlan is the Team Plan lens's vocabulary (oversight_views,
// oversight_service, flagged_schools).
type TeamPlan struct {
	// LeadRole is the role whose team lens this piece draws.
	LeadRole string `json:"lead_role"`
	// LensTabs is the lens strip the role holds, on the Team Plan.
	LensTabs []Tab `json:"lens_tabs"`
	// OwnerTabs are the two tabs before the officers: Whole team, My Work.
	OwnerTabs []Tab `json:"owner_tabs"`
	// ActivityTabs is the activity family strip.
	ActivityTabs []Tab `json:"activity_tabs"`
	// ZeroKPIs are the headline tiles over no work.
	ZeroKPIs []KPI `json:"zero_kpis"`
	// EvidenceLink: the role may open the Evidence Centre.
	EvidenceLink bool `json:"evidence_link"`
	// LiveActivityStatuses are the statuses build_items reads.
	LiveActivityStatuses []string `json:"live_activity_statuses"`
	// NotPlannedStatuses leave the month's planned schools (flagged).
	NotPlannedStatuses []string `json:"not_planned_statuses"`
	// FilterKeys are the advanced filters (read_filters).
	FilterKeys []string `json:"filter_keys"`
	// QueryKeysNotPassed are the keys the feed never passes to a page.
	QueryKeysNotPassed []string `json:"query_keys_not_passed"`
	// Items is what the lens's work is built and drawn from.
	Items ItemRules `json:"items"`
	// Flagged is team_flagged_schools' and the urgent classifier's.
	Flagged FlaggedRules `json:"flagged"`
	// Coverage is the Schools & Coverage lens's vocabulary.
	Coverage CoverageRules `json:"coverage"`
	// Readers are what the lens draws for each role its door opens for.
	Readers map[string]Reader `json:"readers"`
	// LensKPILabels are the tiles' labels on the country and region lenses.
	LensKPILabels map[string][]string `json:"lens_kpi_labels"`
}

// Reader is one role's Team Plan: the scope it reads ("pl", "country",
// "region"), whether its page opens on the planning lens, its lens strip,
// whether the Send controls show, the Evidence Centre link, and which names
// link to their record.
type Reader struct {
	Scope        string          `json:"scope"`
	Planning     bool            `json:"planning"`
	Lenses       map[string]bool `json:"lenses"`
	LensTabs     []Tab           `json:"lens_tabs"`
	MayDelegate  bool            `json:"may_delegate"`
	EvidenceLink bool            `json:"evidence_link"`
	OpenActivity bool            `json:"open_activity"`
	OpenSchool   bool            `json:"open_school"`
	OpenDistrict bool            `json:"open_district"`
	OpenCluster  bool            `json:"open_cluster"`
}

// Family is one activity family of the strip: its key and types.
type Family struct {
	Key   string   `json:"key"`
	Types []string `json:"types"`
}

// ItemRules are build_items', risk_service's, the four tables' and the
// completion columns' vocabularies.
type ItemRules struct {
	VisitTypes                []string          `json:"visit_types"`
	TrainingTypes             []string          `json:"training_types"`
	ClusterMeetingTypes       []string          `json:"cluster_meeting_types"`
	Families                  []Family          `json:"families"`
	PartnerOnlyStatuses       []string          `json:"partner_only_statuses"`
	CompletedWorkStatuses     []string          `json:"completed_work_statuses"`
	OfficerCompletedStatuses  []string          `json:"officer_completed_statuses"`
	NeverOverdue              []string          `json:"never_overdue"`
	CompanionGoneStatuses     []string          `json:"companion_gone_statuses"`
	PurposeLabels             map[string]string `json:"purpose_labels"`
	GeneralIntervention       string            `json:"general_intervention"`
	OperatingStatuses         []string          `json:"operating_statuses"`
	OnlineTrainingTypes       []string          `json:"online_training_types"`
	Online                    string            `json:"online"`
	ClusterMealsRateKey       string            `json:"cluster_meals_rate_key"`
	GroupTrainingMealsRateKey string            `json:"group_training_meals_rate_key"`
	Words                     struct {
		NotInSF         string `json:"not_in_sf"`
		FinishedEarly   string `json:"finished_early"`
		MissingSF       string `json:"missing_sf"`
		MissingEvidence string `json:"missing_evidence"`
		MissingBoth     string `json:"missing_both"`
	} `json:"words"`
	Risk RiskRules `json:"risk"`
}

// RiskRules are risk_service's thresholds and status vocabularies.
type RiskRules struct {
	PostFieldStatuses          []string `json:"post_field_statuses"`
	EvidenceExpectedStatuses   []string `json:"evidence_expected_statuses"`
	SalesforceExpectedStatuses []string `json:"salesforce_expected_statuses"`
	IASettledStatuses          []string `json:"ia_settled_statuses"`
	PaymentSettledStatuses     []string `json:"payment_settled_statuses"`
	EvidenceGraceDays          int      `json:"evidence_grace_days"`
	RescheduleLimit            int      `json:"reschedule_limit"`
	IAVerificationGraceDays    int      `json:"ia_verification_grace_days"`
	PaymentGraceDays           int      `json:"payment_grace_days"`
	PartnerScheduleGraceDays   int      `json:"partner_schedule_grace_days"`
}

// FlaggedRules are team_flagged_schools' and urgent_attention's.
type FlaggedRules struct {
	Precedence                 map[string]int `json:"precedence"`
	VisitTypes                 []string       `json:"visit_types"`
	TrainingTypes              []string       `json:"training_types"`
	IAVerifiedStatuses         []string       `json:"ia_verified_statuses"`
	SchoolTrainingTypes        []string       `json:"school_training_types"`
	SchoolTrainingDoneStatuses []string       `json:"school_training_done_statuses"`
	ClusterTrainingTypes       []string       `json:"cluster_training_types"`
	ClusterCreditStatuses      []string       `json:"cluster_credit_statuses"`
	TrainedTypes               []string       `json:"trained_types"`
	ActiveActionStates         []string       `json:"active_action_states"`
}

var rules = mustRules(rulesJSON)

func mustRules(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("planningoversight: rules.json: %v", err))
	}
	for _, key := range []string{teamKey, countryKey} {
		if r.Pages[key].Path == "" {
			panic("planningoversight: rules.json has no " + key + " page")
		}
	}
	if r.TeamPlan.LeadRole == "" || len(r.TeamPlan.OwnerTabs) != 2 || len(r.TeamPlan.ActivityTabs) == 0 || len(r.TeamPlan.LiveActivityStatuses) == 0 {
		panic("planningoversight: rules.json has no team plan")
	}
	return r
}
