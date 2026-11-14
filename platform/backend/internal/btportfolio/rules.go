// Package btportfolio is the Business Transformation engine the BT pages
// read: who may see which cases, loans and lending partners
// (apps.business_transformation.services.scoped_cases, scoped_loans,
// scoped_mfis, filter_loans), the reporting period a filter selects
// (_selected_period_bounds), and the governed portfolio figures
// (portfolio_metrics over lending_ledger.portfolio_ratios and loan_position).
// It reads the existing ledger's postings and never writes.
//
// The doors, permissions, role sets and labels are exported to rules.json by
// `manage.py export_bt_rules`;
// apps/business_transformation/test_bt_rules_export.py fails when the two
// differ.
package btportfolio

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

//go:embed rules.json
var rulesJSON []byte

// Rules is the exported BT rule set.
var Rules = func() (r struct {
	Roles map[string]struct {
		Pages       []string `json:"pages"`
		Permissions []string `json:"permissions"`
	} `json:"roles"`
	UgandaWideRoles     []string          `json:"uganda_wide_roles"`
	SummaryOnlyRoles    []string          `json:"summary_only_roles"`
	MfiRoles            []string          `json:"mfi_roles"`
	NavRole             string            `json:"nav_role"`
	DistrictLinkRoles   []string          `json:"district_profile_roles"`
	SchoolLinkRoles     []string          `json:"school_profile_roles"`
	PositiveImpact      []string          `json:"positive_impact"`
	CaseStatuses        [][2]string       `json:"case_statuses"`
	OpenCaseStatuses    []string          `json:"open_case_statuses"`
	RecommendationKinds [][2]string       `json:"recommendation_kinds"`
	LoanStatuses        [][2]string       `json:"loan_statuses"`
	SalesforceStatuses  [][2]string       `json:"salesforce_statuses"`
	IAStatuses          [][2]string       `json:"ia_statuses"`
	ImpactStatuses      [][2]string       `json:"impact_statuses"`
	MetricLabels        map[string]string `json:"metric_labels"`
	Portfolio           struct {
		FinancialHealth       string      `json:"financial_health"`
		GovernmentRequirement string      `json:"government_requirement"`
		DeliveredStatuses     []string    `json:"delivered_statuses"`
		OpenSupportStatuses   []string    `json:"open_support_statuses"`
		AssignmentStatuses    [][2]string `json:"assignment_statuses"`
		ReleasedStatuses      []string    `json:"released_statuses"`
		SchoolTypes           [][2]string `json:"school_types"`
		PageSizes             []int       `json:"page_sizes"`
	} `json:"portfolio"`
	Loans struct {
		ApplicationStatuses    [][2]string `json:"application_statuses"`
		RepaymentStatuses      [][2]string `json:"repayment_statuses"`
		RepaymentFrequencies   [][2]string `json:"repayment_frequencies"`
		ApplicationUpdateRoles []string    `json:"application_update_roles"`
		DisbursedStatuses      []string    `json:"disbursed_statuses"`
		AtRiskRepayment        []string    `json:"at_risk_repayment"`
		RowLimit               int         `json:"row_limit"`
	} `json:"loans"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.CaseStatuses) == 0 || r.Loans.RowLimit == 0 {
		panic(fmt.Sprintf("btportfolio: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Opens is whether the role may open page.
func Opens(role, page string) bool {
	return slices.Contains(Rules.Roles[role].Pages, page)
}

// Holds is has_permission for a BT permission.
func Holds(p auth.Principal, permission string) bool {
	return slices.Contains(Rules.Roles[p.ActiveRole].Permissions, permission)
}

// UgandaWide is whether the role reads the whole Uganda portfolio.
func UgandaWide(role string) bool { return slices.Contains(Rules.UgandaWideRoles, role) }

// SummaryOnly is whether the role reads only aggregates.
func SummaryOnly(role string) bool { return slices.Contains(Rules.SummaryOnlyRoles, role) }

// MfiUser is whether the role is a lending partner's.
func MfiUser(role string) bool { return slices.Contains(Rules.MfiRoles, role) }

// Label is a choice's words, or the value itself.
func Label(choices [][2]string, value string) string {
	for _, c := range choices {
		if c[0] == value {
			return c[1]
		}
	}
	return value
}
