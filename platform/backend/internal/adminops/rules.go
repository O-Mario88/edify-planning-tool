// Package adminops is the Admin's platform-operations registers: Support
// Tickets (/admin-ops/support), System Incidents (/admin-ops/incidents) and
// the Maintenance Calendar (/admin-ops/maintenance), as the existing pages
// draw them (apps.admin_ops.views and pages/admin_ops/) and the app's feed
// reads them (apps.mobile_feed). Triage, resolving, acknowledging and the
// incident's own page stay with the existing application.
//
// The doors, labels and limits are exported to rules.json by
// `manage.py export_admin_ops_rules`;
// apps/admin_ops/test_admin_ops_rules_export.py fails when the two differ.
package adminops

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Pages map[string]struct {
		Roles map[string]struct {
			Page bool `json:"page"`
		} `json:"roles"`
	} `json:"pages"`
	TicketStatuses   map[string]string `json:"ticket_statuses"`
	TicketCategories map[string]string `json:"ticket_categories"`
	// ReportRoles open Report a Problem; TicketCategoryChoices are its
	// categories in their order.
	ReportRoles              []string          `json:"report_roles"`
	TicketCategoryChoices    [][2]string       `json:"ticket_category_choices"`
	ClosedTicketStatuses     []string          `json:"closed_ticket_statuses"`
	ResolvableTicketStatuses []string          `json:"resolvable_ticket_statuses"`
	UntriagedTicketStatus    string            `json:"untriaged_ticket_status"`
	IncidentStatuses         map[string]string `json:"incident_statuses"`
	Severities               map[string]string `json:"severities"`
	WorkItemStatuses         map[string]string `json:"work_item_statuses"`
	WorkItemCategories       map[string]string `json:"work_item_categories"`
	DoneWorkItemStatus       string            `json:"done_work_item_status"`
	MaintenanceCategories    []string          `json:"maintenance_categories"`
	// Repairs are the Data Repair Center's catalogue, in its order.
	Repairs []struct {
		Key, Title, Description, Outcome, Referral string
		Automatic                                  bool
	} `json:"repairs"`
	// Admin My Plan and Admin Planning: the severities in order, the
	// statuses My Plan's sections list, how much closed work it shows, how
	// many open incidents and untriaged tickets Planning lists, the backlog
	// and monitoring statuses, the incident statuses that are no longer
	// open, and the backlog table's page size.
	SeverityChoices        [][2]string `json:"severity_choices"`
	MyPlanStatuses         []string    `json:"my_plan_statuses"`
	RecentlyDone           int         `json:"recently_done"`
	PlanningLimit          int         `json:"planning_limit"`
	BacklogStatus          string      `json:"backlog_status"`
	MonitoringStatus       string      `json:"monitoring_status"`
	ClosedIncidentStatuses []string    `json:"closed_incident_statuses"`
	TablePageSize          int         `json:"table_page_size"`
	// TeamPlans is Team Plans' door (Admin and Impact Assessment), the
	// statuses its plan leaves out, how many rows it reads and shows, and
	// the activity labels.
	TeamPlans struct {
		Roles            []string          `json:"roles"`
		TerminalStatuses []string          `json:"terminal_statuses"`
		PageSize         int               `json:"page_size"`
		ReadLimit        int               `json:"read_limit"`
		ActivityTypes    map[string]string `json:"activity_types"`
	} `json:"team_plans"`
	Limits struct {
		Tickets         int `json:"tickets"`
		Incidents       int `json:"incidents"`
		MaintenanceWork int `json:"maintenance_work"`
	} `json:"limits"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Pages) == 0 || len(r.TicketStatuses) == 0 || r.Limits.Tickets == 0 || r.UntriagedTicketStatus == "" || len(r.TeamPlans.Roles) == 0 || r.TeamPlans.ReadLimit == 0 {
		panic(fmt.Sprintf("adminops: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// label is a choice's display, or the stored value when it is not one
// (get_FOO_display).
func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}
