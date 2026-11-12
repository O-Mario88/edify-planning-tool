// Package coreoversight is Core School Oversight as the app opens it
// (/core-schools-oversight/), owned by Go: the Core schools of the reader's
// scope analysed for a year, with the same filters, figures, tabs, lists and
// pages as the existing page (apps.frontend.views.core_oversight_views,
// apps.core_schools.intelligence and the reads behind it, and
// templates/pages/oversight/core_schools_oversight.html), as the app's feed
// reads it (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_core_oversight_rules`;
// apps/core_schools/test_core_oversight_rules_export.py fails when the two
// differ.
package coreoversight

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Doors is what a role may do on the page, by the page's own gates.
type Doors struct {
	// Page: require_page_permission("core_schools_oversight").
	Page bool `json:"page"`
	// School: a school's name is a link to its profile.
	School bool `json:"school"`
	// Review: a Potential Champion carries the Champion review.
	Review bool `json:"review"`
}

// Champion is Champion readiness's words and the official rule's statuses.
type Champion struct {
	Order              []string `json:"order"`
	Champion           string   `json:"champion"`
	Potential          string   `json:"potential"`
	Progressing        string   `json:"progressing"`
	NotYet             string   `json:"not_yet"`
	Insufficient       string   `json:"insufficient"`
	LatestAvg          float64  `json:"latest_avg"`
	StoredChampion     []string `json:"stored_champion"`
	ChampionType       string   `json:"champion_type"`
	ConfirmedSSA       string   `json:"confirmed_ssa"`
	ClosedStatus       string   `json:"closed_status"`
	CleanEvidence      string   `json:"clean_evidence"`
	PlanClosedStatuses []string `json:"plan_closed_statuses"`
	PackageWorkKinds   []string `json:"package_work_kinds"`
	SlotDoneStatuses   []string `json:"slot_done_statuses"`
	PackageWorkSlots   int      `json:"package_work_slots"`
}

// Attention is what a school is listed for (intelligence._attention).
type Attention struct {
	Order         []string `json:"order"`
	Declined      string   `json:"declined"`
	Critical      string   `json:"critical"`
	NoSSA         string   `json:"no_ssa"`
	Package       string   `json:"package"`
	Handover      string   `json:"handover"`
	Candidate     string   `json:"candidate"`
	CriticalBelow float64  `json:"critical_below"`
}

// Change is apps.ssa.change_rules' classifications.
type Change struct {
	Improved         string `json:"improved"`
	Declined         string `json:"declined"`
	NoChange         string `json:"no_change"`
	MaintainedStrong string `json:"maintained_strong"`
	NotComparable    string `json:"not_comparable"`
}

// Rules is rules.json.
type Rules struct {
	Doors              map[string]Doors `json:"doors"`
	FeedOpensPage      bool             `json:"feed_opens_page"`
	NotPassedQueryKeys []string         `json:"not_passed_query_keys"`
	TablePageSize      int              `json:"table_page_size"`
	// Tabs, the trajectory filters, the sorts and the groupings are
	// [key, label] in the page's order.
	Tabs                      [][2]string       `json:"tabs"`
	PlanTabs                  []string          `json:"plan_tabs"`
	TrajectoryFilters         [][2]string       `json:"trajectory_filters"`
	Sorts                     [][2]string       `json:"sorts"`
	Groupings                 [][2]string       `json:"groupings"`
	TrajectoryLabels          map[string]string `json:"trajectory_labels"`
	TrajectoryTones           map[string]string `json:"trajectory_tones"`
	Change                    Change            `json:"change"`
	Champion                  Champion          `json:"champion"`
	Attention                 Attention         `json:"attention"`
	ProgramLeadRole           string            `json:"program_lead_role"`
	CoreTypes                 []string          `json:"core_types"`
	SchoolTypes               map[string]string `json:"school_types"`
	OperatingStatuses         []string          `json:"operating_statuses"`
	CurrentSSAStatuses        []string          `json:"current_ssa_statuses"`
	ConfirmedStatus           string            `json:"confirmed_status"`
	SSAInterventions          [][2]string       `json:"ssa_interventions"`
	HandoverUnscheduled       []string          `json:"handover_unscheduled"`
	HandoverScheduled         []string          `json:"handover_scheduled"`
	HandoverCompleted         string            `json:"handover_completed"`
	DeliveredStatuses         []string          `json:"delivered_statuses"`
	ClusterSessionTypes       []string          `json:"cluster_session_types"`
	TrainingTypes             []string          `json:"training_types"`
	RecommendationStates      map[string]string `json:"recommendation_states"`
	RecommendationShownStates []string          `json:"recommendation_shown_states"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	r := Rules{}
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("coreoversight: rules.json: %v", err))
	}
	if len(r.Tabs) == 0 || r.TablePageSize <= 0 || len(r.Champion.Order) == 0 || len(r.Attention.Order) == 0 {
		panic("coreoversight: rules.json is missing the page's tabs, page size or readings")
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// keyed reports whether key is one of pairs' keys, and its label.
func keyed(pairs [][2]string, key string) (string, bool) {
	for _, p := range pairs {
		if p[0] == key {
			return p[1], true
		}
	}
	return "", false
}

// interventionLabel is SsaIntervention's label, else the key as
// key.replace("_", " ").title() writes it.
func interventionLabel(key string) string {
	if label, ok := keyed(rules.SSAInterventions, key); ok {
		return label
	}
	return pyTitle(replaceUnderscores(key))
}

// interventionDisplay is get_intervention_display: the label, else the
// stored value.
func interventionDisplay(key string) string {
	if label, ok := keyed(rules.SSAInterventions, key); ok {
		return label
	}
	return key
}
