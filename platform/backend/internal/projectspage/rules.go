// Package projectspage is the Special Projects page (/projects): the
// projects a reader may see with the page's filters, its figures, one tab
// per project with the open project's card, and the budget, intervention,
// attention, selected-project, follow-up and partner panels, as the existing
// page draws them (apps.frontend.views.extended_views.projects_list_view,
// apps.projects.dashboard_service.get_dashboard and pages/projects/index.html)
// and the app's feed reads them (apps.mobile_feed).
//
// It reads; it writes nothing. The vocabularies it is built from are the
// existing ones, exported to rules.json by
// `manage.py export_projects_page_rules`;
// apps/projects/test_projects_page_rules_export.py fails when the two differ.
package projectspage

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

// Doors are what a role is given on the page.
type Doors struct {
	Page     bool            `json:"page"`
	Create   bool            `json:"create"`
	Export   bool            `json:"export"`
	Strip    *Strip          `json:"strip"`
	Profiles bool            `json:"profiles"`
	Opens    map[string]bool `json:"opens"`
}

var rules = func() (r struct {
	Doors                    map[string]Doors    `json:"doors"`
	Categories               [][2]string         `json:"categories"`
	StatusFilters            [][2]string         `json:"status_filters"`
	StatusFilterLabels       map[string][]string `json:"status_filter_labels"`
	DeliveredStatuses        []string            `json:"delivered_statuses"`
	NotInPlanStatuses        []string            `json:"not_in_plan_statuses"`
	SSATypes                 []string            `json:"ssa_types"`
	TrainingTypes            []string            `json:"training_types"`
	VisitTypes               []string            `json:"visit_types"`
	DisbursedPaymentStatuses []string            `json:"disbursed_payment_statuses"`
	Interventions            [][2]string         `json:"interventions"`
	MetricLabels             []string            `json:"metric_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("projectspage: rules.json: %v", err))
	}
	if len(r.Doors) == 0 || len(r.MetricLabels) != 12 || len(r.Categories) == 0 {
		panic("projectspage: rules.json lacks its doors, figures or project types")
	}
	return r
}()

// PagePath is the page's door.
const PagePath = "/projects"

func in(list []string, s string) bool { return slices.Contains(list, s) }

// label is a choice's label, or ok false when it is not one of them.
func label(choices [][2]string, value string) (string, bool) {
	for _, c := range choices {
		if c[0] == value {
			return c[1], true
		}
	}
	return "", false
}
