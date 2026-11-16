// Package cpdlearning builds the HR Professional Development Dashboard
// (/cpd-learning): the year's PD figures, the course tracker, HR's five
// action queues, every eligible person's Staff Development Fund position,
// the roles' default allocations, the status and fund charts, the sign-off
// snapshot and the upcoming and overdue courses
// (apps.frontend.views.hr_views.cpd_learning_view,
// apps.professional_development.hr_dashboard_service.HRPDDashboardService
// .get_dashboard and partials/hr/pd_dashboard/body.html, as the existing
// feed reads them).
//
// It reads; it never writes. It hands the page on for a Programme Lead (the
// team view), a Regional VP held to a region, a reader with no staff
// profile, a query it does not know or a value it cannot read, a request
// waiting at the supervisor stage that is not the reader's own (the
// supervisor queue draws it), and a table longer than one page.
//
// The doors and words are exported to rules.json by `manage.py
// export_cpd_learning_rules`; apps/professional_development/
// test_cpd_learning_rules_export.py fails when the two differ.
package cpdlearning

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

type roleRules struct {
	Page             bool `json:"page"`
	TeamView         bool `json:"team_view"`
	AdjustAllocation bool `json:"adjust_allocation"`
	SignOff          bool `json:"sign_off"`
	StaffLinks       bool `json:"staff_links"`
	Strip            any  `json:"strip"`
}

var rules = func() (r struct {
	Roles                         map[string]roleRules `json:"roles"`
	EligibleRoles                 [][2]string          `json:"eligible_roles"`
	Statuses                      map[string]string    `json:"statuses"`
	CourseTypes                   map[string]string    `json:"course_types"`
	NextActions                   map[string]string    `json:"next_actions"`
	CommittedStatuses             []string             `json:"committed_statuses"`
	FundedTypes                   []string             `json:"funded_types"`
	NotStartedStatuses            []string             `json:"not_started_statuses"`
	InProgressStatuses            []string             `json:"in_progress_statuses"`
	PendingCertificateStatuses    []string             `json:"pending_certificate_statuses"`
	EmployeeDoneStatuses          []string             `json:"employee_done_statuses"`
	SignedOffStatuses             []string             `json:"signed_off_statuses"`
	PendingAccountabilityStatuses []string             `json:"pending_accountability_statuses"`
	StatusBuckets                 [][2]string          `json:"status_buckets"`
	Reminders                     [][2]string          `json:"reminders"`
	FundStatusLabels              map[string]string    `json:"fund_status_labels"`
	NotAppliedStatuses            []string             `json:"not_applied_statuses"`
	FundAppliedStatuses           []string             `json:"fund_applied_statuses"`
	FundProcessingStatuses        []string             `json:"fund_processing_statuses"`
	FundInProgressStatuses        []string             `json:"fund_in_progress_statuses"`
	FundCompletedStatuses         []string             `json:"fund_completed_statuses"`
	CertificateLabels             map[string]string    `json:"certificate_labels"`
	OnBambooHRStatuses            []string             `json:"on_bamboohr_statuses"`
	MetricLabels                  []string             `json:"metric_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("cpdlearning: reading rules.json: %v", err))
	}
	if len(r.MetricLabels) != 8 || len(r.EligibleRoles) == 0 || len(r.FundStatusLabels) != 5 {
		panic("cpdlearning: rules.json lacks the figures' labels, the eligible roles or the fund statuses")
	}
	return r
}()

// The statuses every figure and queue names on its own, and the page's sizes.
const (
	statusDraft         = "draft"
	statusSupervisor    = "submitted_to_supervisor"
	statusEnrollment    = "enrollment_confirmed"
	statusAwaitingHR    = "awaiting_hr_signoff"
	statusClosed        = "completed_closed"
	certificateUploaded = "uploaded"
	tablePageSize       = 50
	queueSample         = 3
	listSample          = 8
	defaultCountry      = "Uganda"
	defaultCurrency     = "USD"
)

// The fund statuses, Not Applied first: who table 2b is for.
var fundOrder = []string{"not_applied", "applied", "processing", "in_progress", "completed"}

func in(set []string, v string) bool { return slices.Contains(set, v) }

func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}

func roleLabel(role string) string {
	for _, pair := range rules.EligibleRoles {
		if pair[0] == role {
			return pair[1]
		}
	}
	return role
}

func eligibleRoles() []string {
	out := make([]string, len(rules.EligibleRoles))
	for i, pair := range rules.EligibleRoles {
		out[i] = pair[0]
	}
	return out
}

// bucket is _bucket: the course status a request's status falls in.
func bucket(status string) string {
	switch {
	case in(rules.NotStartedStatuses, status):
		return "not_started"
	case in(rules.InProgressStatuses, status):
		return "in_progress"
	case in(rules.PendingCertificateStatuses, status):
		return "pending_certificate"
	case in(rules.EmployeeDoneStatuses, status):
		return "completed"
	case in(rules.SignedOffStatuses, status):
		return "signed_off"
	}
	return "inactive"
}

// fundStatus is fund_status: where a person's Staff Development Fund
// request is; nil is Not Applied.
func fundStatus(r *request) string {
	switch {
	case r == nil:
		return "not_applied"
	case in(rules.FundCompletedStatuses, r.status):
		return "completed"
	case in(rules.FundInProgressStatuses, r.status):
		return "in_progress"
	case in(rules.FundProcessingStatuses, r.status):
		return "processing"
	case in(rules.FundAppliedStatuses, r.status):
		return "applied"
	}
	return "not_applied"
}

// certificateStatus is certificate_status.
func certificateStatus(r *request, hasCertificate bool) string {
	switch {
	case r == nil:
		return "none"
	case r.bamboo || in(rules.OnBambooHRStatuses, r.status):
		return "bamboohr"
	case hasCertificate:
		return "uploaded"
	case r.certExpected && (in(rules.FundInProgressStatuses, r.status) || in(rules.FundCompletedStatuses, r.status)):
		return "awaiting"
	}
	return "none"
}

// fundReminder is _fund_reminder's label: to apply, to upload the
// certificate, to confirm it on BambooHR, or a plain reminder.
func fundReminder(status, certificate string) string {
	switch {
	case status == "not_applied":
		return "Remind to Apply"
	case certificate == "awaiting":
		return "Remind: Certificate"
	case certificate == "uploaded":
		return "Remind: BambooHR"
	case status == "processing" || status == "in_progress":
		return "Send Reminder"
	}
	return ""
}
