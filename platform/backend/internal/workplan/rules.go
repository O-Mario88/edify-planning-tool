// Package workplan is the Work Plan (/work-plan) read by Go (M4: "Read: My
// Plan, Work Plan, calendar"): one scoped activity ledger over the selected
// period, with the same approval panel, period tabs, filters, Activity Plan
// Summary, strip, month bands and Detailed Activity Plan as the existing page
// (apps.frontend.views.work_plan_page.build_work_plan_context and
// templates/pages/work_plan, partials/work_plan), as the app's feed reads
// them (apps.mobile_feed).
//
// Every drawer the page opens, the export workbook and the CD → RVP
// submission stay the existing application's: the page only links to them.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_work_plan_rules`; apps/frontend/test_work_plan_rules_export.py
// fails when they differ.
package workplan

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"time"
)

//go:embed rules.json
var rulesJSON []byte

// Section is one link of a workspace strip (build_workspace).
type Section struct {
	Label         string `json:"label"`
	URL           string `json:"url"`
	Active        bool   `json:"active"`
	StartsCluster bool   `json:"starts_cluster"`
}

// Workspace is the strip of a workspace's other pages the page shows
// (partials/_section_nav.html), for a role that has one.
type Workspace struct {
	Key      string    `json:"key"`
	Label    string    `json:"label"`
	Sections []Section `json:"sections"`
}

// Door is what one role may open and do on the page.
type Door struct {
	Page             bool            `json:"page"`
	AddActivity      bool            `json:"add_activity"`
	Export           bool            `json:"export"`
	OperationalAdmin bool            `json:"operational_admin"`
	ActionsEnabled   bool            `json:"actions_enabled"`
	Opens            map[string]bool `json:"opens"`
	Workspace        *Workspace      `json:"workspace"`
}

// TableRules are the Detailed Activity Plan's words (apps.frontend.work_plan_tables).
type TableRules struct {
	NotRecorded           string   `json:"not_recorded"`
	InSchoolTraining      string   `json:"in_school_training"`
	GroupTraining         string   `json:"group_training"`
	ClusterMeeting        string   `json:"cluster_meeting"`
	SchoolVisit           string   `json:"school_visit"`
	CompanionVisitPurpose string   `json:"companion_visit_purpose"`
	General               string   `json:"general"`
	DetailPageParam       string   `json:"detail_page_param"`
	OpenToItsOwner        []string `json:"open_to_its_owner"`
	OnlineTrainingLabel   string   `json:"online_training_label"`
	DetailClusterTypes    []string `json:"detail_cluster_types"`
}

// PairRules are apps.activities.pair_costing's and online_training's.
type PairRules struct {
	CompanionGoneStatuses  []string `json:"companion_gone_statuses"`
	CapturedInVisitNote    string   `json:"captured_in_visit_note"`
	CapturedInTrainingNote string   `json:"captured_in_training_note"`
	OnlineFreeNote         string   `json:"online_free_note"`
	OnlineTrainingTypes    []string `json:"online_training_types"`
	OnlineMode             string   `json:"online_mode"`
}

// NextActionRules are compute_next_action's lists (apps.my_plan.services).
type NextActionRules struct {
	WorkedStatuses               []string `json:"worked_statuses"`
	SubmitNeedsParticipantsTypes []string `json:"submit_needs_participants_types"`
}

// Holiday is one public holiday of the national calendar
// (apps.core.public_holidays.national_holidays).
type Holiday struct {
	Date     string `json:"date"`
	Name     string `json:"name"`
	Label    string `json:"label"`
	Expected bool   `json:"expected"`
	day      time.Time
}

// DayOffRules are apps.activities.day_off's and the holiday calendar.
type DayOffRules struct {
	AwaitingDelivery []string  `json:"awaiting_delivery"`
	EidReachDays     int       `json:"eid_reach_days"`
	NationalCountry  string    `json:"national_country"`
	EidAlFitr        string    `json:"eid_al_fitr"`
	EidAlAdha        string    `json:"eid_al_adha"`
	HolidayYears     [2]int    `json:"holiday_years"`
	Holidays         []Holiday `json:"holidays"`
}

// ApprovalRules are apps.planning.work_plan_approval's.
type ApprovalRules struct {
	ExcludedStatuses []string          `json:"excluded_statuses"`
	Country          string            `json:"country"`
	Issues           map[string]string `json:"issues"`
	Statuses         [][2]string       `json:"statuses"`
}

// Metric is one strip figure's registry entry.
type Metric struct {
	Key   string `json:"key"`
	Label string `json:"label"`
	Unit  string `json:"unit"`
}

// Rules are the page's exported vocabularies.
type Rules struct {
	Doors                      map[string]Door        `json:"doors"`
	QueryKeysNotPassed         []string               `json:"query_keys_not_passed"`
	HiddenTerminalStatuses     []string               `json:"hidden_terminal_statuses"`
	AtRiskOpenStatuses         []string               `json:"at_risk_open_statuses"`
	PendingApprovalWFRStatuses []string               `json:"pending_approval_wfr_statuses"`
	WFRLabels                  map[string]string      `json:"wfr_labels"`
	FlagLabels                 map[string]string      `json:"flag_labels"`
	ViewTabLabels              map[string]string      `json:"view_tab_labels"`
	ScopeTabLabels             [][2]string            `json:"scope_tab_labels"`
	ScopeLabels                map[string]string      `json:"scope_labels"`
	TeamScopeLabel             string                 `json:"team_scope_label"`
	OwnScopeLabel              string                 `json:"own_scope_label"`
	SchoolGroupLabel           string                 `json:"school_group_label"`
	NonSchoolGroupLabel        string                 `json:"non_school_group_label"`
	PairBucketSuffix           map[string]string      `json:"pair_bucket_suffix"`
	CompletedWorkStatuses      []string               `json:"completed_work_statuses"`
	VisitTypes                 []string               `json:"visit_types"`
	TrainingTypes              []string               `json:"training_types"`
	ClusterMeetingTypes        []string               `json:"cluster_meeting_types"`
	Statuses                   [][2]string            `json:"statuses"`
	ActivityTypes              [][2]string            `json:"activity_types"`
	DeliveryTypes              [][2]string            `json:"delivery_types"`
	FieldChoices               map[string][][2]string `json:"field_choices"`
	VisitPurposeLabels         map[string]string      `json:"visit_purpose_labels"`
	SSAAlignmentLabels         [][2]string            `json:"ssa_alignment_labels"`
	Table                      TableRules             `json:"table"`
	Pairs                      PairRules              `json:"pairs"`
	NextAction                 NextActionRules        `json:"next_action"`
	DayOff                     DayOffRules            `json:"day_off"`
	Approval                   ApprovalRules          `json:"approval"`
	PlanningCountry            string                 `json:"planning_country"`
	Strip                      []Metric               `json:"strip"`
	choice                     map[string]map[string]string
}

// stripFigures is the strip's length (build_work_plan_context).
const stripFigures = 6

var rules = mustRules()

func mustRules() Rules {
	var r Rules
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("workplan: rules.json: %v", err))
	}
	if len(r.Strip) != stripFigures {
		panic("workplan: rules.json: the strip is not the page's six figures")
	}
	r.choice = map[string]map[string]string{}
	for field, pairs := range r.FieldChoices {
		m := map[string]string{}
		for _, pair := range pairs {
			if _, seen := m[pair[0]]; !seen {
				m[pair[0]] = pair[1]
			}
		}
		r.choice[field] = m
	}
	for i := range r.DayOff.Holidays {
		day, err := time.Parse(time.DateOnly, r.DayOff.Holidays[i].Date)
		if err != nil {
			panic(fmt.Sprintf("workplan: rules.json: holiday %q: %v", r.DayOff.Holidays[i].Date, err))
		}
		r.DayOff.Holidays[i].day = day
	}
	for role, door := range r.Doors {
		if door.Workspace == nil {
			continue
		}
		for _, s := range door.Workspace.Sections {
			if s.StartsCluster || door.Workspace.Key == "ia" {
				// partials/_section_nav.html draws a divider or the Impact
				// Assessment strip for these, which Go does not draw yet.
				panic(fmt.Sprintf("workplan: rules.json: %s's workspace strip is one Go does not draw", role))
			}
		}
	}
	return r
}

// display is a choice field's get_FOO_display(): the label, else the value.
func display(field, value string) string {
	if label, ok := rules.choice[field][value]; ok {
		return label
	}
	return value
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

func valueIn(pairs [][2]string, value string) bool {
	for _, p := range pairs {
		if p[0] == value {
			return true
		}
	}
	return false
}
