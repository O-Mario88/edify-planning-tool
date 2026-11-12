// Package activities makes the first save Go owns: scheduling a school visit
// from Planning's Schedule drawer (docs/migration/27), exactly 27.3's case.
// Everything else is handed on to the existing application (ErrHandOn).
//
// The rules are the existing ones, read line by line (27.6): the view
// (apps/frontend/views/planning_views.py schedule_action_view) and the
// create (apps/activities/services.py _create) with every module they call
// for this case. Their vocabularies are exported to rules.json by
// `python manage.py export_schedule_visit_rules`; words that live in
// templates and the few literals inside `_create` are written here, each
// with the line it comes from.
package activities

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Rules are the exported vocabularies.
type Rules struct {
	Doors struct {
		Drawer       []string `json:"drawer"`
		Requesters   []string `json:"requesters"`
		AdminRole    string   `json:"admin_role"`
		AdminRefusal string   `json:"admin_refusal"`
	} `json:"doors"`
	Purposes struct {
		Staff            []string          `json:"staff"`
		Retired          []string          `json:"retired"`
		Labels           map[string]string `json:"labels"`
		ActivityTypes    map[string]string `json:"activity_types"`
		InterventionFree []string          `json:"intervention_free"`
	} `json:"purposes"`
	SalesforceTrainingKinds []string          `json:"salesforce_training_kinds"`
	CostedAs                map[string]string `json:"costed_as"`
	Gate                    struct {
		CoreRuleTypes         []string          `json:"core_rule_types"`
		ClientRuleTypes       []string          `json:"client_rule_types"`
		OutreachOnlyTypes     []string          `json:"outreach_only_types"`
		OutreachActivityTypes []string          `json:"outreach_activity_types"`
		FollowUpVisitTypes    []string          `json:"follow_up_visit_types"`
		SSASupportVisitTypes  []string          `json:"ssa_support_visit_types"`
		InSchoolSupportTypes  []string          `json:"in_school_support_types"`
		CompanionPurpose      string            `json:"companion_purpose"`
		SchoolTypeLabels      map[string]string `json:"school_type_labels"`
	} `json:"gate"`
	DuplicateGoneStatuses []string `json:"duplicate_gone_statuses"`
	LedgerCreditedTypes   []string `json:"ledger_credited_types"`
	ClosedStatuses        []string `json:"closed_statuses"`
	OperatingStatuses     []string `json:"operating_statuses"`
	ClosedSchoolMessage   string   `json:"closed_school_message"`
	CalendarBlocksRefuse  bool     `json:"calendar_blocks_refuse"`
	DefaultCountry        string   `json:"default_country"`
	Alignment             struct {
		EngineVersion             string   `json:"engine_version"`
		PriorityDepth             int      `json:"priority_depth"`
		StrongScore               float64  `json:"strong_score"`
		CriticalScore             float64  `json:"critical_score"`
		CurrentSSAFYs             int      `json:"current_ssa_fys"`
		CollectionKinds           []string `json:"collection_kinds"`
		NotSchoolImprovementKinds []string `json:"not_school_improvement_kinds"`
	} `json:"alignment"`
	Engine struct {
		Weights           [][2]json.RawMessage `json:"weights"`
		MinPeers          int                  `json:"min_peers"`
		PersistenceWindow int                  `json:"persistence_window"`
		WeaknessThreshold float64              `json:"weakness_threshold"`
		Interventions     [][2]string          `json:"interventions"`
	} `json:"engine"`
	Batch struct {
		FieldRoles          []string `json:"field_roles"`
		FieldRoleAliases    []string `json:"field_role_aliases"`
		HQZone              []string `json:"hq_zone"`
		EligibleTypes       []string `json:"eligible_types"`
		PoolExtraTypes      []string `json:"pool_extra_types"`
		NonFundableStatuses []string `json:"non_fundable_statuses"`
	} `json:"batch"`
	Move struct {
		OverdueEvent string `json:"overdue_event"`
		DayOffEvent  string `json:"day_off_event"`
		SavedMessage string `json:"saved_message"`
	} `json:"move"`

	weights []weight
	labels  map[string]string
	order   []string
}

type weight struct {
	name  string
	value float64
}

var rules = mustRules()

func mustRules() Rules {
	var r Rules
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("activities: rules.json: %v", err))
	}
	for _, pair := range r.Engine.Weights {
		var w weight
		if json.Unmarshal(pair[0], &w.name) != nil || json.Unmarshal(pair[1], &w.value) != nil {
			panic("activities: rules.json: a weight is not [name, value]")
		}
		r.weights = append(r.weights, w)
	}
	r.labels = map[string]string{}
	for _, pair := range r.Engine.Interventions {
		r.order = append(r.order, pair[0])
		r.labels[pair[0]] = pair[1]
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// The in-scope purposes (27.3), and the literals of `_create` and the view.
var (
	// inScopePurposes are 27.3's six; anything else is handed on.
	inScopePurposes = []string{
		"training_follow_up", "ssa_support", "donor_visit", "story_gathering", "school_invitation", "social_visit",
	}
	// ssaCollectionTypes: schedule_action_view 2291–2298 and _create
	// 2362–2369 (the same list).
	ssaCollectionTypes = []string{
		"baseline_ssa_visit", "school_visit_ssa_collection", "cluster_training_ssa_collection",
		"cluster_meeting_ssa_review", "partner_ssa_collection", "core_assessment_visit",
	}
	// identicalExcluded: _create's duplicate test (3304).
	identicalExcluded = []string{"cancelled", "rejected", "deferred"}
)

const (
	// The answer's words (schedule_action_view 2515–2517) and its links.
	scheduledMessage = "School visit scheduled. It is on your My Plan — keep planning."
	myPlanLabel      = "Open My Plan"
	// _no_scheduling_permission_message for every role but the Admin, who
	// reads doors.admin_refusal.
	noPermission = "Access Denied: You do not have permission to schedule activities."
)
