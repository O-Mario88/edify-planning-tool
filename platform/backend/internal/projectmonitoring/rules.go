// Package projectmonitoring is Project Monitoring (/projects/monitoring): the
// schools a reader may watch in each live Special Project, one project a tab,
// with the page's filters, its figures, the reader's workload line and the
// open project's table of schools, as the existing page draws them
// (apps.frontend.views.extended_views.project_monitoring_view,
// apps.projects.monitoring and pages/projects/monitoring.html) and the app's
// feed reads them (apps.mobile_feed).
//
// This first piece answers the page while no project work exists in view:
// no project activity, no partner hand-over, no school allocation, every
// school awaiting the Project Coordinator. Anything else the page can show
// (the work lines, their costs and doors, allocations, a measured cohort, a
// table past one page, a paused project's note for the coordinator) is passed
// on to the existing application (served=false) rather than guessed.
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_project_monitoring_rules`;
// apps/projects/test_project_monitoring_rules_export.py fails when the two
// differ.
package projectmonitoring

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// LinkTab is one link of a workspace strip, as the feed reads it.
type LinkTab struct {
	Label  string `json:"label"`
	Href   string `json:"href"`
	Active bool   `json:"active"`
}

// Strip is the workspace strip under the filters (partials/_section_nav.html).
type Strip struct {
	Label   string    `json:"label"`
	Scrolls bool      `json:"scrolls"`
	Tabs    []LinkTab `json:"tabs"`
}

// Doors is what a role is given on the page, by the page's own gates.
type Doors struct {
	Page     bool   `json:"page"`
	Profiles bool   `json:"profiles"`
	Strip    *Strip `json:"strip"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Doors                  map[string]Doors  `json:"doors"`
	WholeProjectRoles      []string          `json:"whole_project_roles"`
	CoordinatorRole        string            `json:"coordinator_role"`
	WithdrawAnySchoolRoles []string          `json:"withdraw_any_school_roles"`
	LiveStatuses           []string          `json:"live_statuses"`
	OpenStatuses           []string          `json:"open_statuses"`
	StatusLabels           map[string]string `json:"status_labels"`
	PlanLabels             map[string]string `json:"plan_labels"`
	ExecLabels             map[string]string `json:"exec_labels"`
	RowStatusLabels        map[string]string `json:"status_labels_row"`
	ImpactLabels           map[string]string `json:"impact_labels"`
	StageFilters           [][2]string       `json:"stage_filters"`
	RowFilters             [][3]string       `json:"row_filters"`
	General                string            `json:"general"`
	GeneralIntervention    string            `json:"general_intervention"`
	Interventions          [][2]string       `json:"interventions"`
	Abbreviations          map[string]string `json:"abbreviations"`
	Confirmed              string            `json:"confirmed"`
	ScoreMin               float64           `json:"score_min"`
	ScoreMax               float64           `json:"score_max"`
	Measured               []string          `json:"measured"`
	OperatingStatuses      []string          `json:"operating_statuses"`
	PageSize               int               `json:"page_size"`
	// PastSchoolRules is partners.handover_policy.past_school_rules for a
	// project: a Champion school may be handed to a partner too, so every
	// school of an open project takes a tick box.
	PastSchoolRules bool `json:"project_handovers_past_school_rules"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Doors) == 0 || len(r.LiveStatuses) == 0 ||
		len(r.Interventions) == 0 || len(r.StageFilters) == 0 || len(r.RowFilters) != 5 ||
		r.RowFilters[0][0] != "district" || r.PageSize <= 0 || r.CoordinatorRole == "" || !r.PastSchoolRules || r.ScoreMax <= r.ScoreMin {
		panic(fmt.Sprintf("projectmonitoring: the embedded rules are unreadable: %v", err))
	}
	for _, key := range []string{"not_planned"} {
		if r.PlanLabels[key] == "" {
			panic("projectmonitoring: the embedded rules lack the plan label " + key)
		}
	}
	for _, key := range []string{"awaiting_coordinator"} {
		if r.RowStatusLabels[key] == "" {
			panic("projectmonitoring: the embedded rules lack the status label " + key)
		}
	}
	if r.ExecLabels["none"] == "" {
		panic("projectmonitoring: the embedded rules lack the execution label none")
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// isIntervention is value in SsaIntervention.values.
func isIntervention(value string) bool {
	for _, c := range rules.Interventions {
		if c[0] == value {
			return true
		}
	}
	return false
}

// interventionLabel is dict(SsaIntervention.choices).get(code, fallback).
func interventionLabel(code string) (string, bool) {
	for _, c := range rules.Interventions {
		if c[0] == code {
			return c[1], true
		}
	}
	return "", false
}
