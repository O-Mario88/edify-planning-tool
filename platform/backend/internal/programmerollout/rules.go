// Package programmerollout is the Programme Lead's Programme Rollout
// (/programme-rollout): the team's trainings by SSA intervention, by course
// and by officer, the trainings of the next 30 days, and the Regional Lead's
// observations, as the existing page draws it
// (apps.frontend.views.programme_rollout_views over
// apps.analytics.programme_rollout_service and
// partials/programme_rollout/trainings.html) and the app's feed reads it.
//
// The doors, statuses, types and words are exported to rules.json by
// `manage.py export_programme_rollout_rules`;
// apps/frontend/test_programme_rollout_rules_export.py fails when the two
// differ.
package programmerollout

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"regexp"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles                 []string          `json:"page_roles"`
	ProgramLead               string            `json:"program_lead"`
	LeadChoosers              []string          `json:"lead_choosers"`
	Views                     []string          `json:"views"`
	DefaultView               string            `json:"default_view"`
	UpcomingDays              int               `json:"upcoming_days"`
	UpcomingRows              int               `json:"upcoming_rows"`
	TrainingTypes             []string          `json:"training_types"`
	SchoolTrainingTypes       []string          `json:"school_training_types"`
	ClusterTrainingTypes      []string          `json:"cluster_training_types"`
	NotPlannedStatuses        []string          `json:"not_planned_statuses"`
	LiveStatuses              []string          `json:"live_statuses"`
	InReviewStatuses          []string          `json:"in_review_statuses"`
	CompletedStatuses         []string          `json:"completed_statuses"`
	ClusterCreditStatuses     []string          `json:"cluster_credit_statuses"`
	InterventionOrder         []string          `json:"intervention_order"`
	InterventionLabels        map[string]string `json:"intervention_labels"`
	InterventionAbbreviations map[string]string `json:"intervention_abbreviations"`
	StatusLabels              map[string]string `json:"status_labels"`
	TypeLabels                map[string]string `json:"type_labels"`
	OperatingStatuses         []string          `json:"operating_statuses"`
	ObservationKind           string            `json:"observation_kind"`
	PageSize                  int               `json:"page_size"`
	OfficerRows               int               `json:"officer_rows"`
	SSA                       struct {
		ConfirmedStatus               string      `json:"confirmed_status"`
		AwaitingRecordStatuses        []string    `json:"awaiting_record_statuses"`
		CollectionTypes               []string    `json:"collection_types"`
		UnscheduledAssignmentStatuses []string    `json:"unscheduled_assignment_statuses"`
		MatrixInterventions           [][3]string `json:"matrix_interventions"`
	} `json:"ssa"`
	Spiritual struct {
		Interventions           []string    `json:"interventions"`
		WeakestCount            int         `json:"weakest_count"`
		ChristianTransformation string      `json:"christian_transformation"`
		CCSELCode               string      `json:"cc_sel_code"`
		CampCatalogueType       string      `json:"camp_catalogue_type"`
		Families                [][2]string `json:"families"`
	} `json:"spiritual"`
	Observations struct {
		Criteria              []string          `json:"criteria"`
		ChangeRecommendations []string          `json:"change_recommendations"`
		RecommendationLabels  map[string]string `json:"recommendation_labels"`
		RatingLabels          map[string]string `json:"rating_labels"`
		DelivererRows         int               `json:"deliverer_rows"`
	} `json:"observations"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.TrainingTypes) == 0 || r.PageSize == 0 || len(r.SSA.CollectionTypes) == 0 || len(r.SSA.MatrixInterventions) == 0 || len(r.Spiritual.Interventions) != 2 || len(r.Spiritual.Families) != 3 ||
		len(r.Observations.Criteria) == 0 || !criteriaAreColumns(r.Observations.Criteria) {
		panic(fmt.Sprintf("programmerollout: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// abbr is intervention_abbr: the abbreviation, else the value itself.
func abbr(code string) string {
	if a, ok := rules.InterventionAbbreviations[code]; ok {
		return a
	}
	return code
}

// criteriaAreColumns is whether every rubric criterion names a rating
// column, as the observation query reads them by name.
func criteriaAreColumns(criteria []string) bool {
	for _, c := range criteria {
		if !ratingColumn.MatchString(c) {
			return false
		}
	}
	return true
}

var ratingColumn = regexp.MustCompile(`^rating_[a-z_]+$`)
