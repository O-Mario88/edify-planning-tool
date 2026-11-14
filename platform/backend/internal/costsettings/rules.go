// Package costsettings builds the Cost Catalogue (/cost-settings) and its
// read-only door, Cost Intelligence (/cost-intelligence): the published
// country operational rate card's rates, the reviews of activity costs
// waiting for the reference layer, and how every governed activity is
// costed (apps.frontend.views.finance_views.cost_settings_view and
// pages/cost_settings/index.html).
//
// It reads; it never writes. Every drawer the page opens (adding a cost,
// editing a rate, carrying a card forward) stays with the existing
// application, and so does any page this package hands on: no published
// card, an empty card, a provisional card, a year the filter does not offer,
// another query, more than seven pages in a table, or an Activity Catalogue
// costing profile the engine does not know.
//
// The activity's recipe is internal/costing, Go's port of the existing
// engine. The roles, names and limits are exported to rules.json by
// `manage.py export_cost_settings_rules`;
// apps/budget/test_cost_settings_rules_export.py fails when the two differ.
package costsettings

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode"
)

//go:embed rules.json
var rulesJSON []byte

type role struct {
	Doors     []string `json:"doors"`
	Reference bool     `json:"reference"`
	Manage    bool     `json:"manage"`
}

var rules = func() (r struct {
	Roles             map[string]role      `json:"roles"`
	Country           string               `json:"country"`
	OperationalKind   string               `json:"operational_kind"`
	PublishedStatus   string               `json:"published_status"`
	KindLabels        map[string]string    `json:"kind_labels"`
	ActiveItemStatus  string               `json:"active_item_status"`
	CostingProfiles   map[string][2]string `json:"costing_profiles"`
	ActivityTypes     map[string]string    `json:"activity_types"`
	DeliveryMethods   map[string]string    `json:"delivery_methods"`
	Interventions     map[string]string    `json:"interventions"`
	ReviewReasons     map[string]string    `json:"review_reasons"`
	ReviewQueueStatus string               `json:"review_queue_status"`
	ReviewQueueLimit  int                  `json:"review_queue_limit"`
	TablePageSize     int                  `json:"table_page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("costsettings: rules.json: %v", err))
	}
	if r.TablePageSize < 1 || r.ReviewQueueLimit < 1 || r.Country == "" {
		panic("costsettings: rules.json lacks its page size, queue limit or country")
	}
	return r
}()

// The two doors and the names their sidebar entries carry.
const (
	SettingsPath     = "/cost-settings"
	IntelligencePath = "/cost-intelligence"
)

var titles = map[string]string{SettingsPath: "Cost Catalogue", IntelligencePath: "Cost Intelligence"}

func mayOpen(r, path string) bool {
	return slices.Contains(rules.Roles[r].Doors, path)
}

// zone is the application's TIME_ZONE: timezone.localdate().
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic("costsettings: " + err.Error())
	}
	return z
}()

// display is a choice field's get_FOO_display(): its label, or the value
// itself; a null value is "None", as the template writes it.
func display(choices map[string]string, value *string) string {
	if value == nil {
		return "None"
	}
	if label, ok := choices[*value]; ok {
		return label
	}
	return *value
}

// pyTitle is Python's str.title().
func pyTitle(s string) string {
	out := []rune{}
	previousCased := false
	for _, r := range s {
		switch {
		case unicode.IsLetter(r) && !previousCased:
			out = append(out, unicode.ToTitle(r))
		case unicode.IsLetter(r):
			out = append(out, unicode.ToLower(r))
		default:
			out = append(out, r)
		}
		previousCased = unicode.IsLetter(r)
	}
	return string(out)
}

// currency is the template's currency filter: a whole number of shillings
// with thousands commas; nothing is "0".
func currency(n *int64) string {
	if n == nil {
		return "0"
	}
	s := fmt.Sprint(*n)
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return sign + s
}

func collapse(s string) string { return strings.Join(strings.Fields(s), " ") }
