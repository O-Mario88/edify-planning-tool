// Package fundapprovals builds Fund Approvals (/fund-approvals): a week of
// a team's fund plans for the Program Lead (and the Country Director's
// queue of the requests that reach them, and the Admin's view of every
// officer's): the strip of the week's money, the queue of officers, the
// selected officer's ledger and action row, the month's plan-against-
// approved progress and approval rate, the budget mix and the latest
// decisions (apps.frontend.views.extended_views.pl_fund_approvals_view,
// apps.fund_requests.pl_approval_service.get_pl_fund_approvals and
// partials/finance/fund_workspace.html, as the existing feed reads them).
//
// It reads; it never writes. The existing page writes a missing weekly
// request as it opens (generate_weekly_fund_request); Go hands the page on
// whenever an officer with work that week has no request, so the existing
// application makes that write. It also hands the page on for a reader
// with partner invoices to confirm, a reader with no team, a query it does
// not know (an export), a year, month or week that is not plainly one, a
// team with more than 200 requests and no request in the month (the
// recent decisions then read an unordered 200), and a ledger longer than
// one page.
//
// Two orders follow the database's rather than a rule: officers whose week
// costs the same keep the order the team is read in (an unordered read, in
// the existing application too), and a district tie in an officer's work
// goes to the district met first (Python's set order, which varies).
//
// The doors, statuses, hints and words are exported to rules.json by
// `manage.py export_fund_approvals_rules`; apps/fund_requests/
// test_fund_approvals_rules_export.py fails when the two differ.
package fundapprovals

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
	Doors                map[string]Doors     `json:"doors"`
	CDApprovalRoles      []string             `json:"cd_approval_roles"`
	StatusLabels         map[string][2]string `json:"status_labels"`
	Hints                map[string]string    `json:"hints"`
	VisitTypes           []string             `json:"visit_types"`
	TrainingTypes        []string             `json:"training_types"`
	SSAVisitTypes        []string             `json:"ssa_visit_types"`
	ClusterMeetingTypes  []string             `json:"cluster_meeting_types"`
	ClusterTrainingTypes []string             `json:"cluster_training_types"`
	Months               []string             `json:"months"`
	ActivityTypes        map[string]string    `json:"activity_types"`
	MetricLabels         []string             `json:"metric_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("fundapprovals: reading rules.json: %v", err))
	}
	if len(r.Months) != 13 || len(r.MetricLabels) != 4 {
		panic("fundapprovals: rules.json lacks the months or the figures' labels")
	}
	return r
}()

// statusLabel is WEEKLY_STATUS_LABELS for a request's status ("" for none),
// "Awaiting CCEO Send" for one it does not name.
func statusLabel(status string) string {
	if pair, ok := rules.StatusLabels[status]; ok {
		return pair[0]
	}
	return "Awaiting CCEO Send"
}

// category is pl_approval_service._category.
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
