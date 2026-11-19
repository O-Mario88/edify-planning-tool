// Package financedesks builds the Accountant's desk pages
// (apps.frontend.views.finance_operating_views and
// templates/pages/accounts/*.html) as the existing feed reads them:
// accountability, advances to disburse, the finance audit log, budget
// amendments, the cleared ledger, returned corrections and variance reviews.
package financedesks

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// role is what one role is given on the desks (export_finance_desks_rules).
type role struct {
	Desks      map[string]bool `json:"desks"`
	OpenSchool bool            `json:"open_school"`
}

var rules = func() (r struct {
	Roles                   map[string]role   `json:"roles"`
	ActivityTypes           map[string]string `json:"activity_types"`
	NotInPlanStatuses       []string          `json:"not_in_plan_statuses"`
	IAVerifiedStatuses      []string          `json:"ia_verified_statuses"`
	NoSalesforceRecordTypes []string          `json:"no_salesforce_record_types"`
	PartnerPaidStatuses     []string          `json:"partner_paid_statuses"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("financedesks: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.ActivityTypes) == 0 {
		panic("financedesks: rules.json lacks the doors or the activity types")
	}
	return r
}()

// typeLabel is get_activity_type_display: the choice's words, or the stored
// value.
func typeLabel(value string) string {
	if label, ok := rules.ActivityTypes[value]; ok {
		return label
	}
	return value
}
