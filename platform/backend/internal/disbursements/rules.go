// Package disbursements builds the Fund Disbursement Dashboard
// (/disbursements): the Accountant's consolidated fund queue for a month
// (monthly fund plans, weekly advances, partner payments and reimbursement
// claims), the selected item's funding breakdown and action row, the
// month's allocation and disbursement rate, the disbursement mix and the
// latest money movements (apps.frontend.views.finance_views
// .disbursements_view, apps.fund_requests.disbursement_dashboard_service
// .get_disbursement_dashboard and partials/finance/fund_workspace.html, as
// the existing feed reads them).
//
// It reads; it never writes. It hands the page on for a query it does not
// know (an export, a breakdown's page), a year or month that is not plainly
// one, and a breakdown or ledger longer than one page.
//
// The doors, statuses and words are exported to rules.json by `manage.py
// export_disbursements_rules`; apps/fund_requests/test_disbursements_rules_
// export.py fails when the two differ.
package disbursements

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Doors is what a role is given: the page and its export.
type Doors struct {
	Page   bool `json:"page"`
	Export bool `json:"export"`
}

var rules = func() (r struct {
	Doors                      map[string]Doors  `json:"doors"`
	StatusOptions              []string          `json:"status_options"`
	StatusSort                 map[string]int    `json:"status_sort"`
	MonthlyPendingApproval     []string          `json:"monthly_pending_approval"`
	MonthlyPendingDisbursement []string          `json:"monthly_pending_disbursement"`
	MonthlyReturned            []string          `json:"monthly_returned"`
	MoneyMovedAdvanceStatuses  []string          `json:"money_moved_advance_statuses"`
	PartnerPayableStatuses     []string          `json:"partner_payable_statuses"`
	NonFundableStatuses        []string          `json:"non_fundable_statuses"`
	CategoryOrder              []string          `json:"category_order"`
	VisitTypes                 []string          `json:"visit_types"`
	SSAVisitTypes              []string          `json:"ssa_visit_types"`
	ClusterMeetingTypes        []string          `json:"cluster_meeting_types"`
	ClusterTrainingTypes       []string          `json:"cluster_training_types"`
	TrainingTypes              []string          `json:"training_types"`
	LineTypeLabels             map[string]string `json:"line_type_labels"`
	MixColours                 map[string]string `json:"mix_colours"`
	Months                     []string          `json:"months"`
	ActivityTypes              map[string]string `json:"activity_types"`
	MetricLabels               []string          `json:"metric_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("disbursements: reading rules.json: %v", err))
	}
	if len(r.Months) != 13 || len(r.MetricLabels) != 4 {
		panic("disbursements: rules.json lacks the months or the figures' labels")
	}
	return r
}()

// The queue's statuses (disbursement_dashboard_service.STATUS_OPTIONS).
const (
	pendingApproval     = "Pending Approval"
	pendingDisbursement = "Pending Disbursement"
	held                = "Held"
	disbursed           = "Disbursed"
	awaitingRecon       = "Awaiting Reconciliation"
	returned            = "Returned"
	closed              = "Closed"
)

// monthlyStatus is _monthly_status.
func monthlyStatus(status string, accountabilitySubmitted, accountabilityReviewed bool) string {
	switch {
	case slices.Contains(rules.MonthlyPendingApproval, status):
		return pendingApproval
	case slices.Contains(rules.MonthlyPendingDisbursement, status):
		return pendingDisbursement
	case status == "held":
		return held
	case status == "disbursed":
		if accountabilitySubmitted && !accountabilityReviewed {
			return awaitingRecon
		}
		return disbursed
	case slices.Contains(rules.MonthlyReturned, status):
		return returned
	case status == "closed":
		return closed
	}
	return pendingApproval
}

// WeeklyStatus is a weekly request's stage label as weekly_status_buckets
// gives it: its status, whether an advance behind it waits on accountability,
// and whether the request's accountability was submitted and reviewed.
func WeeklyStatus(status string, pendingAccountability, accountabilitySubmitted, accountabilityReviewed bool) string {
	return weeklyStatus(status, pendingAccountability, accountabilitySubmitted, accountabilityReviewed)
}

// weeklyStatus is _weekly_status.
func weeklyStatus(status string, pendingAccountability, accountabilitySubmitted, accountabilityReviewed bool) string {
	switch status {
	case "pending_responsible_confirmation":
		return pendingApproval
	case "confirmed_for_advance":
		return pendingDisbursement
	case "disbursed":
		if pendingAccountability || (accountabilitySubmitted && !accountabilityReviewed) {
			return awaitingRecon
		}
		return disbursed
	case "returned_by_accountant", "returned":
		return returned
	case "accounted":
		return closed
	}
	return pendingApproval
}

// category is pl_approval_service._category for a plan's activity.
func category(activityType, deliveryType, programmeType string) string {
	switch {
	case programmeType == "admin":
		return "Admin Budget"
	case slices.Contains(rules.VisitTypes, activityType):
		if deliveryType == "partner" {
			return "Partner School Visits"
		}
		return "Staff School Visits"
	case slices.Contains(rules.SSAVisitTypes, activityType):
		return "SSA Support Visits"
	case slices.Contains(rules.ClusterMeetingTypes, activityType):
		return "Cluster Meetings"
	case slices.Contains(rules.ClusterTrainingTypes, activityType):
		return "Cluster Trainings"
	case slices.Contains(rules.TrainingTypes, activityType):
		return "In-School Trainings"
	case activityType == "field_event":
		return "Field Events"
	}
	return "Other"
}

// activityTypeLabel is get_activity_type_display(): the choice's name, or
// the stored value when it is no choice.
func activityTypeLabel(t string) string {
	if label, ok := rules.ActivityTypes[t]; ok {
		return label
	}
	return t
}
