// Package ccelead is the CCE leadership registers
// (apps.frontend.views.cce_leadership_views, pages/cce_leadership/
// workspace.html) as the app's feed reads them, starting with the monthly CCE
// reports (/cce-leadership/reports). Writing, submitting and reviewing a
// report stay with the existing application.
//
// The doors, strips, buttons, figure labels, report statuses and the month
// reporting started are exported to rules.json by
// `manage.py export_cce_leadership_rules`;
// apps/cce_leadership/test_cce_leadership_rules_export.py fails when the two
// differ.
package ccelead

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on one register.
type Role struct {
	Page    bool               `json:"page"`
	Strip   *decisionlog.Strip `json:"strip"`
	Drawers []string           `json:"drawers"`
}

var rules = func() (r struct {
	Pages map[string]struct {
		Roles map[string]Role `json:"roles"`
	} `json:"pages"`
	MetricLabels    map[string]string `json:"metric_labels"`
	ReportStatuses  map[string]string `json:"report_statuses"`
	ReportTones     map[string]string `json:"report_tones"`
	ReportingStarts string            `json:"reporting_starts"`
	RatingFields    []string          `json:"rating_fields"`
	Recommendations map[string]string `json:"recommendations"`
	ActivityTypes   map[string]string `json:"activity_types"`
	EngagementKinds [][2]string       `json:"engagement_kinds"`
	ShareableKinds  []string          `json:"shareable_kinds"`
	CoachingKinds   [][2]string       `json:"coaching_kinds"`
	CoachingStates  [][2]string       `json:"coaching_states"`
	OneToOneKind    string            `json:"one_to_one_kind"`
	OneToOneDueDay  int               `json:"one_to_one_due_day"`
	Cadence         struct {
		Rules []struct {
			Kind, Label, Expectation, Per, Window string
			EveryDays                             *int `json:"every_days"`
		} `json:"rules"`
		StateLabels            map[string]string `json:"state_labels"`
		StateTones             map[string]string `json:"state_tones"`
		StateOrder             map[string]int    `json:"state_order"`
		DueSoonDays            int               `json:"due_soon_days"`
		QuarterDueSoonDays     int               `json:"quarter_due_soon_days"`
		AnnualWindowOpensMonth int               `json:"annual_window_opens_month"`
	} `json:"cadence"`
	Saves struct {
		ObservationCriteria []([3]string) `json:"observation_criteria"`
		RecommendationOrder [][2]string   `json:"recommendation_choices"`
		ReportSections      []([3]string) `json:"report_sections"`
		TrainingTypes       []string      `json:"training_types"`
		NotLiveStatuses     []string      `json:"not_live_statuses"`
		LookbackDays        int           `json:"observation_lookback_days"`
		LookaheadDays       int           `json:"observation_lookahead_days"`
		CompletedStatuses   []string      `json:"completed_work_statuses"`
		CoachingFollowUps   []string      `json:"coaching_follow_up_types"`
		LivePlanStatuses    []string      `json:"live_plan_statuses"`
		InformedVerdicts    []string      `json:"informed_verdicts"`
		RatingScale         []([2]any)    `json:"rating_scale"`
	} `json:"saves"`
	HelperFigureChars  int      `json:"helper_figure_chars"`
	PageSize           int      `json:"page_size"`
	QueryKeysNotPassed []string `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Pages) == 0 || len(r.ReportStatuses) == 0 ||
		r.ReportingStarts == "" || r.PageSize <= 0 {
		panic(fmt.Sprintf("ccelead: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// reportingStarts is services.REPORTING_STARTS: the first month a report was
// owed through the platform.
var reportingStarts = func() time.Time {
	t, err := time.Parse(time.DateOnly, rules.ReportingStarts)
	if err != nil {
		panic("ccelead: " + err.Error())
	}
	return t
}()
