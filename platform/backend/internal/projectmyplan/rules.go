// Package projectmyplan builds the Special Projects My Plan (/projects/my-plan):
// the reader's project work in the chosen week, month, quarter or year, by
// list (school visits, trainings, cluster meetings, partner work), with the
// year's figures, the day's work, what needs attention, the budget and
// workflow counts and the next step
// (apps.frontend.views.extended_views.special_projects_my_plan_view,
// apps.projects.my_plan_service.get_my_plan and
// partials/projects/my_plan_workspace.html, as the existing feed reads them).
//
// It reads; it never writes. It hands the page on for the plan's file (the
// export query) and any query it does not know. The doors and words are
// exported to rules.json by `manage.py export_project_my_plan_rules`;
// apps/projects/test_project_my_plan_rules_export.py fails when the two
// differ.
package projectmyplan

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page  bool            `json:"page"`
		Strip json.RawMessage `json:"strip"`
	} `json:"roles"`
	MetricLabels             []string          `json:"metric_labels"`
	ActivityTypes            map[string]string `json:"activity_types"`
	EvidenceStatuses         map[string]string `json:"evidence_statuses"`
	Interventions            map[string]string `json:"interventions"`
	ActiveExclusions         []string          `json:"active_exclusions"`
	ReturnedStates           []string          `json:"returned_states"`
	ReviewStates             []string          `json:"review_states"`
	DeliveredStatuses        []string          `json:"delivered_statuses"`
	OfficerCompletedStatuses []string          `json:"officer_completed_statuses"`
	VisitTypes               []string          `json:"visit_types"`
	TrainingTypes            []string          `json:"training_types"`
	MeetingTypes             []string          `json:"meeting_types"`
	CompleteLabel            string            `json:"complete_label"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("projectmyplan: reading rules.json: %v", err))
	}
	if len(r.MetricLabels) != 12 || len(r.Roles) == 0 || r.CompleteLabel == "" {
		panic("projectmyplan: rules.json lacks the figures' labels, the doors or the complete label")
	}
	return r
}()

func in(set []string, v string) bool { return slices.Contains(set, v) }

func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}

// statusOptions is the status filter's choices, as get_my_plan lists them.
var statusOptions = [][2]string{
	{"scheduled", "Scheduled"}, {"in_progress", "In progress"}, {"returned", "Returned"},
	{"review", "In review"}, {"completed", "Completed"}, {"rescheduled", "Rescheduled"},
}

// evidenceLabels is _row's evidence_map; a state it does not name reads as
// the field's own name for it.
var evidenceLabels = map[string]string{
	"none": "Not submitted", "uploaded": "Awaiting review", "accepted": "Submitted",
	"returned": "Returned", "rejected": "Rejected",
}

// quality is platform_engine._quality's label for a count of records.
func quality(n int) string {
	switch {
	case n == 0:
		return "No data"
	case n < 5:
		return "Very limited"
	case n < 10:
		return "Limited"
	case n < 30:
		return "Moderate"
	}
	return "Strong"
}
