package daypool

import (
	"errors"
	"fmt"
	"strings"
)

// Day marks (pricing.PRIMARY_DAY, SECONDARY_DAY, MIXED_DAY).
const (
	PrimaryDay   = "primary"
	SecondaryDay = "secondary"
	MixedDay     = "mixed"
)

var (
	errNoTarget = errors.New("target_district is required")
)

// isFieldRole is districts.is_field_role: one of the two roles that hold a
// primary district of their own, by its value or the field's own words.
func isFieldRole(role string) bool {
	return in(rules.District.FieldRoles, role) || in(rules.District.FieldRoleAliases, norm(role))
}

// HQDistrictType is districts.hq_district_type: a head-office visit is
// primary inside the Kampala, Wakiso and Mukono zone, secondary elsewhere.
func HQDistrictType(districtName string) string {
	if in(rules.District.HQZone, norm(districtName)) {
		return rules.District.Primary
	}
	return rules.District.Secondary
}

// ResolveDistrictType is districts.resolve_district_type on plain values:
// the person's role, their primary district (name or id, "" for none) and
// the district visited. A field role without a primary district is refused,
// as the existing rule refuses it.
func ResolveDistrictType(role, primaryDistrict, targetDistrict string) (string, error) {
	if norm(targetDistrict) == "" {
		return "", errNoTarget
	}
	if isFieldRole(role) {
		if norm(primaryDistrict) == "" {
			return "", fmt.Errorf("a %s must have exactly one primary district configured before a visit can be priced", role)
		}
		if norm(primaryDistrict) == norm(targetDistrict) {
			return rules.District.Primary, nil
		}
		return rules.District.Secondary, nil
	}
	return HQDistrictType(targetDistrict), nil
}

// HoldsFieldRole is districts.holds_field_role: field staff by the roles an
// account holds; an account listing none reads its active role.
func HoldsFieldRole(roles []string, activeRole string) bool {
	if len(roles) == 0 {
		return isFieldRole(activeRole)
	}
	for _, role := range roles {
		if isFieldRole(role) {
			return true
		}
	}
	return false
}

// AccommodationKeyForUser is districts.accommodation_key_for_user: the
// second rate when any role the account holds is on the management list,
// else the CCEO's; an account listing no roles reads its active role.
func AccommodationKeyForUser(roles []string, activeRole string) string {
	if len(roles) == 0 {
		roles = []string{activeRole}
	}
	for _, role := range roles {
		if in(rules.District.ManagementAccommodationRoles, role) {
			return rules.Pricing.ManagementAccommodationKey
		}
	}
	return rules.Pricing.AccommodationKey
}

// DayDistrictMark is pricing.day_district_mark: Primary, Secondary or Mixed
// for one person's day from the district type of every activity on it. An
// activity with no type is primary.
func DayDistrictMark(districtTypes []string) string {
	primary, secondary := false, false
	for _, t := range districtTypes {
		switch t {
		case "", PrimaryDay:
			primary = true
		case SecondaryDay:
			secondary = true
		}
	}
	if secondary {
		if primary {
			return MixedDay
		}
		return SecondaryDay
	}
	return PrimaryDay
}

// PricingDistrictType is pricing.pricing_district_type: a Mixed day pays the
// secondary district's rates.
func PricingDistrictType(mark string) string {
	if mark == PrimaryDay {
		return PrimaryDay
	}
	return SecondaryDay
}

func isAccommodationKey(key string) bool {
	return key == rules.Pricing.AccommodationKey || key == rules.Pricing.ManagementAccommodationKey
}

// DayKeys is pricing.day_keys: the rates one day fetches, with the
// traveller's accommodation; a key that is neither accommodation rate is
// the CCEO's. The day home fetches neither a night nor a dinner.
func DayKeys(districtType, accommodationKey string, returnDay bool) []string {
	if !isAccommodationKey(accommodationKey) {
		accommodationKey = rules.Pricing.AccommodationKey
	}
	keys := []string{}
	for _, key := range rules.Pricing.RequiredKeys[districtType] {
		if key == rules.Pricing.AccommodationKey {
			key = accommodationKey
		}
		if returnDay && in(rules.Pricing.ReturnDayDroppedKeys, key) {
			continue
		}
		keys = append(keys, key)
	}
	return keys
}

// WithRateAliases is reference.with_rate_aliases: a rate card that answers a
// renamed key from the first of its old keys it still carries.
func WithRateAliases(rates map[string]int64) map[string]int64 {
	if len(rates) == 0 {
		return rates
	}
	resolved := make(map[string]int64, len(rates))
	for key, amount := range rates {
		resolved[key] = amount
	}
	for key, oldKeys := range rules.RateAliases {
		if _, ok := resolved[key]; ok {
			continue
		}
		for _, old := range oldKeys {
			if amount, ok := rates[old]; ok {
				resolved[key] = amount
				break
			}
		}
	}
	return resolved
}

// Rate is one component of a day's pool, in whole shillings.
type Rate struct {
	Key    string
	Amount int64
}

// Pool is a day's components in the order the existing code builds them.
type Pool []Rate

// Amounts is the pool as {key: amount}, the shape of rate_snapshot.
func (p Pool) Amounts() map[string]int64 {
	out := make(map[string]int64, len(p))
	for _, r := range p {
		out[r.Key] = r.Amount
	}
	return out
}

// Total is daily_pool_amount: the sum of the pool.
func (p Pool) Total() int64 {
	var total int64
	for _, r := range p {
		total += r.Amount
	}
	return total
}

// MissingRatesError is the refusal of a day whose rate card lacks a rate it
// needs, worded as the existing application words it.
type MissingRatesError struct {
	DistrictType string
	Missing      []string
}

func (e *MissingRatesError) Error() string {
	return fmt.Sprintf(
		"Cost Catalogue is missing required rate(s) for %s district visits: %s. Ask the CD to add them in Cost Settings.",
		e.DistrictType, strings.Join(e.Missing, ", "))
}

// ComputeDailyPool is pricing.compute_daily_pool: every rate the day needs
// from the card (renamed keys answered by their old ones), plus any optional
// rate the card carries; refused, naming each missing rate, otherwise.
func ComputeDailyPool(rates map[string]int64, districtType, accommodationKey string, returnDay bool) (Pool, error) {
	rates = WithRateAliases(rates)
	required := DayKeys(districtType, accommodationKey, returnDay)
	var missing []string
	for _, key := range required {
		if _, ok := rates[key]; !ok {
			missing = append(missing, key)
		}
	}
	if len(missing) > 0 {
		return nil, &MissingRatesError{DistrictType: districtType, Missing: missing}
	}
	pool := make(Pool, 0, len(required))
	for _, key := range required {
		pool = append(pool, Rate{Key: key, Amount: rates[key]})
	}
	for _, key := range rules.Pricing.OptionalKeys[districtType] {
		if amount, ok := rates[key]; ok {
			pool = append(pool, Rate{Key: key, Amount: amount})
		}
	}
	return pool, nil
}

// AllocateComponent is pricing.allocate_component: total split across n so
// the shares sum to it exactly, the remainder shillings going to the first
// shares. Division floors, as Python's divmod does.
func AllocateComponent(total int64, n int) []int64 {
	if n <= 0 {
		return nil
	}
	base, remainder := total/int64(n), total%int64(n)
	if remainder < 0 {
		base, remainder = base-1, remainder+int64(n)
	}
	shares := make([]int64, n)
	for i := range shares {
		shares[i] = base
		if int64(i) < remainder {
			shares[i]++
		}
	}
	return shares
}

// AllocatePool is pricing.allocate_pool: n shares of the pool, each component
// divided on its own, share i for the i-th member in the caller's order.
func AllocatePool(pool Pool, n int) []map[string]int64 {
	if n <= 0 {
		return nil
	}
	shares := make([]map[string]int64, n)
	for i := range shares {
		shares[i] = make(map[string]int64, len(pool))
	}
	for _, r := range pool {
		for i, amount := range AllocateComponent(r.Amount, n) {
			shares[i][r.Key] = amount
		}
	}
	return shares
}
