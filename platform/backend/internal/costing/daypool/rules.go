// Package costing prices a staff member's day of field work as the existing
// application prices it (docs/migration/35): where the day is spent, the
// rates it fetches, the night away and the day home, and the share of the
// day's pool each piece of work on it carries.
//
// Money stays the existing application's until M12. This package reads and
// compares; it writes nothing. The rules are the existing ones
// (apps.daily_visit_batches.districts, .pricing, .return_day and the day's
// planning in .services), exported with their answers to rules.json and
// vectors.json by `python manage.py export_costing_rules`.
package daypool

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
)

//go:embed rules.json
var rulesJSON []byte

// Rules are the exported vocabularies.
type Rules struct {
	District struct {
		HQZone                       []string `json:"hq_zone"`
		FieldRoles                   []string `json:"field_roles"`
		FieldRoleAliases             []string `json:"field_role_aliases"`
		ManagementAccommodationRoles []string `json:"management_accommodation_roles"`
		Primary                      string   `json:"primary"`
		Secondary                    string   `json:"secondary"`
	} `json:"district"`
	Pricing struct {
		RequiredKeys               map[string][]string `json:"required_keys"`
		OptionalKeys               map[string][]string `json:"optional_keys"`
		AccommodationKey           string              `json:"accommodation_key"`
		ManagementAccommodationKey string              `json:"management_accommodation_key"`
		ReturnDayDroppedKeys       []string            `json:"return_day_dropped_keys"`
		KeyLabels                  map[string]string   `json:"key_labels"`
		MixedTransportLabel        string              `json:"mixed_transport_label"`
		DayMarkLabels              map[string]string   `json:"day_mark_labels"`
	} `json:"pricing"`
	// RateAliases names, for a renamed rate, the old keys that still answer
	// for it, in the order they are tried.
	RateAliases map[string][]string `json:"rate_aliases"`
	// CanonicalRateKeys are the keys a rate card prices with.
	CanonicalRateKeys   []string `json:"canonical_rate_keys"`
	NonFundableStatuses []string `json:"non_fundable_statuses"`
}

var rules = mustRules()

func mustRules() Rules {
	var r Rules
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("costing: rules.json: %v", err))
	}
	if r.District.Primary == "" || r.District.Secondary == "" || r.Pricing.AccommodationKey == "" {
		panic("costing: rules.json is missing the district types or the accommodation key")
	}
	return r
}

// norm is the existing code's _norm: trimmed and case-folded. Folding is
// strings.ToLower, which equals Python's casefold for every district and
// role name the platform holds (ASCII); a name with "ß" would differ.
func norm(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func in(list []string, value string) bool {
	return slices.Contains(list, value)
}
