// Package weeklyrequest builds the Weekly Advance Request page's week
// (/fund-requests/weekly: apps.frontend.views.budget_views.
// weekly_fund_requests_view, _build_fund_requests_context and
// partials/fund_requests/*, as the existing feed reads them): the money chain's
// stages, the filters, the month's request figures, the week's request with
// its submitted ledger and what the reader may do with it, the week's source
// activities, the insights and the totals by period.
//
// It reads; it never writes. The existing page writes a missing request on
// open when the reader's own week holds scheduled work
// (_self_heal_weekly_request); Go hands that page on (owner, 2026-11-16:
// "Keep handing on", the same as Fund Approvals). It also hands on the
// Month, Quarter and Annual horizons, a week with costed lines but no request
// (the budget workspace draws it), a week shared by more than one request in
// view, an export, a reader in an acting appointment and a role shown a
// workspace strip. The doors and words are exported to rules.json by
// `manage.py export_weekly_request_rules`;
// apps/fund_requests/test_weekly_request_rules_export.py fails when the two
// differ.
package weeklyrequest

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

type role struct {
	Page            bool            `json:"page"`
	Strip           json.RawMessage `json:"strip"`
	AddActivity     bool            `json:"add_activity"`
	Export          bool            `json:"export"`
	PaymentAct      bool            `json:"payment_act"`
	ClearsEscalated bool            `json:"clears_escalated"`
	MonthlyRequest  bool            `json:"monthly_request"`
	Reports         bool            `json:"reports"`
}

var rules = func() (r struct {
	Roles                map[string]role   `json:"roles"`
	EveryoneStaff        string            `json:"everyone_staff"`
	NonFundableStatuses  []string          `json:"non_fundable_statuses"`
	StageLabels          []string          `json:"stage_labels"`
	PurposeInterventions map[string]string `json:"purpose_interventions"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("weeklyrequest: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.StageLabels) != 6 || r.EveryoneStaff == "" {
		panic("weeklyrequest: rules.json lacks the doors, the stages or the everyone value")
	}
	return r
}()

func in(set []string, v string) bool { return slices.Contains(set, v) }

// Months as the page's MONTH_MAP and its select name them.
var months = []string{"", "January", "February", "March", "April", "May", "June", "July",
	"August", "September", "October", "November", "December"}

// The month select's order: the fiscal year's, October first.
var fiscalMonths = []int{10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9}

// The request-type and status selects (partials/fund_requests/root.html).
var requestTypes = [][2]string{
	{"", "All types"}, {"school visits", "School Visits"}, {"cluster training", "Cluster Training"},
	{"cluster meetings", "Cluster Meetings"}, {"core visits", "Core Visits"}, {"core trainings", "Core Trainings"},
	{"ssa support", "SSA Support"}, {"partner activities", "Partner Activities"}, {"admin budget", "Admin Budget"},
}

var statusOptions = [][2]string{
	{"", "All statuses"}, {"pending_responsible_confirmation", "Draft"}, {"confirmed_for_advance", "Ready"},
	{"self_funded", "Self-funded"}, {"disbursed", "Disbursed"},
}
