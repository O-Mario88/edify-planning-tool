// Package mypd is My Professional Development (/my-professional-development):
// the reader's PD figures for a year, the current course and its tracker,
// the next actions, the reminders, the messages from HR, the quick actions
// and the course table, as the existing page draws them
// (apps.frontend.views.pd_views.my_professional_development_view,
// apps.professional_development.services.StaffPDService.get_page and
// partials/professional_development/body.html) and the app's feed reads them.
//
// The existing page writes when it is read, and so does this one (owner,
// 2026-11-16: "Same writes"; docs/migration/68 §68.7): the reader's courses
// are moved on by their dates and the reminders that ends are closed
// (PDCourseTrackingService.sync_all), and the year's allocation is made when
// there is none (StaffPDService.get_or_create_allocation). The page is
// passed on to the existing application unless EDIFY_GO_PAGE_WRITES names it.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_my_pd_rules`;
// apps/professional_development/test_my_pd_rules_export.py fails when the
// two differ.
package mypd

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

// Strip is the workspace strip above the filters (partials/_section_nav.html).
type Strip struct {
	Label   string    `json:"label"`
	Scrolls bool      `json:"scrolls"`
	Tabs    []LinkTab `json:"tabs"`
}

// Doors are what a role is given.
type Doors struct {
	Page  bool   `json:"page"`
	Strip *Strip `json:"strip"`
}

var rules = func() (r struct {
	Doors             map[string]Doors  `json:"doors"`
	StatusLabels      map[string]string `json:"status_labels"`
	CourseTypes       map[string]string `json:"course_types"`
	DocumentTypes     map[string]string `json:"document_types"`
	SelfFunded        string            `json:"self_funded"`
	FundedTypes       []string          `json:"funded_types"`
	ActiveStatuses    []string          `json:"active_statuses"`
	ClosedStatuses    []string          `json:"closed_statuses"`
	CommittedStatuses []string          `json:"committed_statuses"`
	TimelineSteps     []string          `json:"timeline_steps"`
	StepIndex         map[string]int    `json:"step_index"`
	NextActions       map[string]string `json:"next_actions"`
	StartingEvent     string            `json:"starting_event"`
	InProgressEvent   string            `json:"in_progress_event"`
	MetricLabels      []string          `json:"metric_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("mypd: rules.json: %v", err))
	}
	if len(r.Doors) == 0 || len(r.MetricLabels) != 8 || len(r.TimelineSteps) != 12 || r.StartingEvent == "" {
		panic("mypd: rules.json lacks its doors, figures, tracker or reminders")
	}
	return r
}()

// PagePath is the page's door.
const PagePath = "/my-professional-development"

func in(list []string, s string) bool { return slices.Contains(list, s) }

// statusLabel is get_status_display(): the label, or the value itself.
func statusLabel(s string) string {
	if l, ok := rules.StatusLabels[s]; ok {
		return l
	}
	return s
}

func courseType(s string) string {
	if l, ok := rules.CourseTypes[s]; ok {
		return l
	}
	return s
}
