// Package costing prices one activity from the rate card: Go's port of
// apps.budget.costing.cost_for_activity, the single source of truth for an
// activity's cost lines.
//
// It reads nothing and writes nothing: CostForActivity is a pure function of
// the activity's planned quantities and the card. Reading the card and
// storing the lines stay with the callers (and, for now, with the existing
// application: Go saves leave their pricing to it).
//
// The rates, labels, aliases, day keys and activity types are exported to
// rules.json by `manage.py export_costing_rules`;
// apps/budget/test_costing_rules_export.py fails when the two differ.
package costing

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"sort"
)

//go:embed rules.json
var rulesJSON []byte

type ruleSet struct {
	CanonicalRates   [][2]string         `json:"canonical_rates"`
	OptionalRateKeys []string            `json:"optional_rate_keys"`
	RateAliases      [][]json.RawMessage `json:"rate_aliases"`
	MealsRateKeys    []string            `json:"meals_rate_keys"`
	Day              struct {
		Required          map[string][]string `json:"required"`
		Optional          map[string][]string `json:"optional"`
		AccommodationKey  string              `json:"accommodation_key"`
		AccommodationKeys []string            `json:"accommodation_keys"`
		DinnerKey         string              `json:"dinner_key"`
		ReturnDayDropped  []string            `json:"return_day_dropped"`
		Labels            map[string]string   `json:"labels"`
	} `json:"day"`
	Types struct {
		ClusterMeeting  []string `json:"cluster_meeting"`
		ClusterTraining []string `json:"cluster_training"`
		Training        []string `json:"training"`
		Visit           []string `json:"visit"`
		SSAWork         []string `json:"ssa_work"`
		CoreWork        []string `json:"core_work"`
	} `json:"types"`
}

// compiled is the rule set in the shapes the recipe asks of it.
type compiled struct {
	rateLabels        map[string]string
	canonicalKeys     []string
	optional          set
	aliases           []alias
	meals             set
	dayRequired       map[string][]string
	dayOptional       map[string][]string
	accommodationKey  string
	accommodationKeys []string
	dinnerKey         string
	returnDayDropped  set
	dayLabels         map[string]string
	clusterMeeting    set
	clusterTraining   set
	training          set
	visit             set
	ssaWork           set
	coreWork          set
}

type alias struct {
	key string
	old []string
}

type set map[string]struct{}

func setOf(keys []string) set {
	s := make(set, len(keys))
	for _, k := range keys {
		s[k] = struct{}{}
	}
	return s
}

func (s set) has(k string) bool {
	_, ok := s[k]
	return ok
}

var rules = mustCompile(rulesJSON)

func mustCompile(raw []byte) compiled {
	c, err := compile(raw)
	if err != nil {
		panic(err)
	}
	return c
}

func compile(raw []byte) (compiled, error) {
	var r ruleSet
	if err := json.Unmarshal(raw, &r); err != nil {
		return compiled{}, fmt.Errorf("costing rules: %w", err)
	}
	c := compiled{
		rateLabels:        map[string]string{},
		optional:          setOf(r.OptionalRateKeys),
		meals:             setOf(r.MealsRateKeys),
		dayRequired:       r.Day.Required,
		dayOptional:       r.Day.Optional,
		accommodationKey:  r.Day.AccommodationKey,
		accommodationKeys: r.Day.AccommodationKeys,
		dinnerKey:         r.Day.DinnerKey,
		returnDayDropped:  setOf(r.Day.ReturnDayDropped),
		dayLabels:         r.Day.Labels,
		clusterMeeting:    setOf(r.Types.ClusterMeeting),
		clusterTraining:   setOf(r.Types.ClusterTraining),
		training:          setOf(r.Types.Training),
		visit:             setOf(r.Types.Visit),
		ssaWork:           setOf(r.Types.SSAWork),
		coreWork:          setOf(r.Types.CoreWork),
	}
	for _, kl := range r.CanonicalRates {
		c.rateLabels[kl[0]] = kl[1]
		c.canonicalKeys = append(c.canonicalKeys, kl[0])
	}
	for _, pair := range r.RateAliases {
		if len(pair) != 2 {
			return compiled{}, fmt.Errorf("costing rules: rate alias %v is not [key, [old…]]", pair)
		}
		var a alias
		if err := json.Unmarshal(pair[0], &a.key); err != nil {
			return compiled{}, fmt.Errorf("costing rules: rate alias key: %w", err)
		}
		if err := json.Unmarshal(pair[1], &a.old); err != nil {
			return compiled{}, fmt.Errorf("costing rules: rate alias %s: %w", a.key, err)
		}
		c.aliases = append(c.aliases, a)
	}
	for _, need := range []string{"primary", "secondary"} {
		if _, ok := c.dayRequired[need]; !ok {
			return compiled{}, fmt.Errorf("costing rules: no %s day", need)
		}
	}
	for _, need := range []string{"group_training_facilitation_fee", "group_training_venue_cost", "partner_meetings", "client_partner_visit", "core_partner_visit"} {
		if _, ok := c.rateLabels[need]; !ok {
			return compiled{}, fmt.Errorf("costing rules: rate %s is not canonical", need)
		}
	}
	for _, key := range c.meals.sorted() {
		if _, ok := c.rateLabels[key]; !ok {
			return compiled{}, fmt.Errorf("costing rules: meals rate %s is not canonical", key)
		}
	}
	return c, nil
}

func (s set) sorted() []string {
	out := make([]string, 0, len(s))
	for k := range s {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// CanonicalRateKeys is the registry's rates in its order.
func CanonicalRateKeys() []string { return append([]string(nil), rules.canonicalKeys...) }

// AccommodationKeys is the two night rates, sorted.
func AccommodationKeys() []string { return append([]string(nil), rules.accommodationKeys...) }

// RateLabel is a canonical rate's catalogue label, or the key itself.
func RateLabel(key string) string {
	if l, ok := rules.rateLabels[key]; ok {
		return l
	}
	return key
}

// WithRateAliases answers renamed keys from the rows the card still carries
// (apps.budget.reference.with_rate_aliases). The card is not changed.
func WithRateAliases(card map[string]int64) map[string]int64 {
	if len(card) == 0 {
		return card
	}
	out := make(map[string]int64, len(card)+len(rules.aliases))
	for k, v := range card {
		out[k] = v
	}
	for _, a := range rules.aliases {
		if _, ok := out[a.key]; ok {
			continue
		}
		for _, old := range a.old {
			if v, ok := card[old]; ok {
				out[a.key] = v
				break
			}
		}
	}
	return out
}

// Alias is a canonical rate and the renamed keys it answers for, in order.
type Alias struct {
	Key string
	Old []string
}

// Aliases is apps.budget.reference.RATE_ALIASES, in its order.
func Aliases() []Alias {
	out := make([]Alias, len(rules.aliases))
	for i, a := range rules.aliases {
		out[i] = Alias{Key: a.key, Old: append([]string(nil), a.old...)}
	}
	return out
}

// IsCanonical is whether key is one of the registry's rates.
func IsCanonical(key string) bool {
	_, ok := rules.rateLabels[key]
	return ok
}

// DayKeys is apps.daily_visit_batches.pricing.day_keys and the optional
// keys after them: the rates one day away fetches in that district, with
// the traveller's night rate (an unknown one is the CCEO's), and without the
// night and the dinner on the day the traveller comes home.
func DayKeys(district, accommodationKey string, returnDay bool) (required, optional []string) {
	return dayKeys(district, accommodationKey, returnDay), append([]string(nil), rules.dayOptional[district]...)
}

// DayLabel is the day line's name (KEY_LABELS), and whether the key is one
// of the day's own rates.
func DayLabel(key string) (string, bool) {
	l, ok := rules.dayLabels[key]
	return l, ok
}
