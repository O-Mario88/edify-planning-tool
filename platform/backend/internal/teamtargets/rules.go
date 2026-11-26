package teamtargets

import (
	_ "embed"
	"encoding/json"
)

// rules.json is written by `manage.py export_team_targets_rules`;
// apps/targets/test_team_targets_rules_export.py fails when the two differ.
//
//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles         []string             `json:"page_roles"`
	ExportRoles       []string             `json:"export_roles"`
	SFRequiredTypes   []string             `json:"sf_required_types"`
	CompletedStatuses []string             `json:"completed_statuses"`
	VisitTypes        []string             `json:"visit_types"`
	LiveProjects      []string             `json:"live_project_statuses"`
	Recommendations   map[string][2]string `json:"recommendations"`
	OrderRanked       string               `json:"order_ranked"`
	CatchUpStatuses   map[string]string    `json:"catchup_status_labels"`
	ActivityTypes     map[string]string    `json:"activity_type_labels"`
	Backlogs          map[string]struct {
		Title, Badge, Tone, Helper string
		Empty                      string `json:"empty_message"`
	} `json:"validation_backlogs"`
	NotInPlan  []string `json:"not_in_plan_statuses"`
	NotStarted []string `json:"not_started_statuses"`
	// ReturnedStatuses are the work a day's drawer leaves out.
	ReturnedStatuses []string          `json:"returned_statuses"`
	RiskEvents       []string          `json:"risk_events"`
	MetricLabels     map[string]string `json:"metric_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic("teamtargets: rules.json: " + err.Error())
	}
	return r
}()
