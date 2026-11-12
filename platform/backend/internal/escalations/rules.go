// Package escalations is the Escalations page (/escalations): the upward
// decision channel as a reader sees it, with the form to raise one level up,
// the escalations awaiting the reader's decision, those they raised, those
// their Programme Leads received and those recently decided, as the existing
// page draws them (apps.frontend.views.escalation_views.escalations_view,
// apps.flags.escalation_service.board, pages/escalations/index.html and
// _table.html) and the app's feed reads them (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_escalations_rules`;
// apps/flags/test_escalations_rules_export.py fails when the two differ.
package escalations

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	// Page opens Escalations at all.
	Page bool `json:"page"`
	// RaisesTo is the level the role escalates to; empty when it cannot.
	RaisesTo string `json:"raises_to"`
	// DecidesFor is the level the role decides for; empty when none.
	DecidesFor string `json:"decides_for"`
	// DecidesAll is Admin: every escalation is theirs to read and decide.
	DecidesAll bool `json:"decides_all"`
	// ReadsCountryBoard is the Country Director's oversight of what the
	// country's Programme Leads received and what it sent up.
	ReadsCountryBoard bool `json:"reads_country_board"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles              map[string]Role   `json:"roles"`
	AddresseeLabels    [][2]string       `json:"addressee_labels"`
	RoleForAddressee   map[string]string `json:"role_for_addressee"`
	ProgrammeLeadLevel string            `json:"programme_lead_level"`
	RegionalLevel      string            `json:"regional_level"`
	Categories         [][2]string       `json:"categories"`
	Decisions          [][2]string       `json:"decisions"`
	Severities         [][2]string       `json:"severities"`
	DefaultSeverity    string            `json:"default_severity"`
	SLADays            map[string]int    `json:"sla_days"`
	Statuses           struct {
		Open, Acknowledged, Resolved string
	} `json:"statuses"`
	PageSize           int      `json:"page_size"`
	QueryKeysNotPassed []string `json:"query_keys_not_passed"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || len(r.AddresseeLabels) == 0 ||
		len(r.Categories) == 0 || len(r.Decisions) == 0 || len(r.Severities) == 0 || len(r.SLADays) == 0 ||
		r.Statuses.Resolved == "" || r.Statuses.Open == "" || r.RegionalLevel == "" || r.PageSize <= 0 {
		panic(fmt.Sprintf("escalations: the embedded rules are unreadable: %v", err))
	}
	return r
}

// lookup is a choice's label, and whether the value is one of the choices.
func lookup(choices [][2]string, value string) (string, bool) {
	for _, c := range choices {
		if c[0] == value {
			return c[1], true
		}
	}
	return "", false
}

// display is dict(choices).get(value, value).
func display(choices [][2]string, value string) string {
	if label, ok := lookup(choices, value); ok {
		return label
	}
	return value
}

// addresseeLabel is ADDRESSEE_LABELS.get(level): "None" in the page's words
// when the level is none, as the template writes a missing value.
func addresseeLabel(level string) string {
	if label, ok := lookup(rules.AddresseeLabels, level); ok {
		return label
	}
	return "None"
}

// slaDays is how long an escalation of a severity may sit open.
func slaDays(severity string) int {
	if days, ok := rules.SLADays[severity]; ok {
		return days
	}
	return rules.SLADays[rules.DefaultSeverity]
}
