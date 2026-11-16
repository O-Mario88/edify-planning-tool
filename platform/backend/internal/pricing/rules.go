// Package pricing prices a stored activity read-only, as the existing single
// cost writer would: it builds the recipe's input from the activity
// (apps.activities.services._costing_input) and runs it against the country
// operational and the regional reference rate cards
// (apps.budget.costing_service.calculate_dual), with the same warnings,
// missing configuration and viability. The recipe is internal/costing.
//
// It reads; it never writes. Saving a price (its lines, snapshot and
// advances), the day a visit shares with others and an in-school Training
// carried by its visit are the existing application's.
//
// The rules are exported to rules.json by `manage.py export_pricing_rules`;
// apps/budget/test_pricing_rules_export.py fails when the two differ.
package pricing

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	CostingProfiles              map[string][2]string `json:"costing_profiles"`
	HQPrimaryDistricts           []string             `json:"hq_primary_districts"`
	FieldRoles                   []string             `json:"field_roles"`
	FieldRoleAliases             []string             `json:"field_role_aliases"`
	ManagementAccommodationRoles []string             `json:"management_accommodation_roles"`
	AccommodationKey             string               `json:"accommodation_key"`
	ManagementAccommodationKey   string               `json:"management_accommodation_key"`
	Country                      string               `json:"country"`
	OperationalKind              string               `json:"operational_kind"`
	ReferenceKind                string               `json:"reference_kind"`
	PublishedStatus              string               `json:"published_status"`
	NonFundableStatuses          []string             `json:"non_fundable_statuses"`
	DailyBatchEligibleTypes      []string             `json:"daily_batch_eligible_types"`
	DayPoolExtraTypes            []string             `json:"day_pool_extra_types"`
	MixedTransportLabel          string               `json:"mixed_transport_label"`
	OnlineTrainingTypes          []string             `json:"online_training_types"`
	OnlineMode                   string               `json:"online_mode"`
	CompanionGoneStatuses        []string             `json:"companion_gone_statuses"`
	RebuildableWeeklyStatuses    []string             `json:"rebuildable_weekly_statuses"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("pricing: rules.json: %v", err))
	}
	if r.AccommodationKey == "" || r.OperationalKind == "" || len(r.FieldRoles) == 0 {
		panic("pricing: rules.json lacks its accommodation rate, card kinds or field roles")
	}
	return r
}()

func in(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// norm is districts._norm: trimmed and case-folded.
func norm(s string) string { return strings.ToLower(strings.TrimSpace(s)) }

// isFieldRole is districts.is_field_role.
func isFieldRole(role string) bool {
	return in(rules.FieldRoles, role) || in(rules.FieldRoleAliases, norm(role))
}

// holdsFieldRole is districts.holds_field_role: any role held, else the
// active one.
func holdsFieldRole(roles []string, active string) bool {
	if len(roles) == 0 {
		return isFieldRole(active)
	}
	for _, r := range roles {
		if isFieldRole(r) {
			return true
		}
	}
	return false
}

// hqDistrictType is districts.hq_district_type.
func hqDistrictType(name string) string {
	for _, d := range rules.HQPrimaryDistricts {
		if norm(d) == norm(name) {
			return "primary"
		}
	}
	return "secondary"
}

// accommodationKeyFor is districts.accommodation_key_for_user (and _role):
// the second rate when any role held is on it, else the CCEO's.
func accommodationKeyFor(roles []string, active string, known bool) string {
	if !known {
		return rules.AccommodationKey
	}
	held := roles
	if len(held) == 0 {
		held = []string{active}
	}
	for _, r := range held {
		if in(rules.ManagementAccommodationRoles, r) {
			return rules.ManagementAccommodationKey
		}
	}
	return rules.AccommodationKey
}
