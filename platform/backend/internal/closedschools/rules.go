// Package closedschools is the Closed Schools page (/schools/closed), the
// archive: the closures a person may read, the three figures above them, the
// year's closure impact for the roles that read it, the search and the
// table's pages, as the existing page draws them
// (apps.frontend.views.school_views.closed_schools_view and
// pages/schools/closed.html) and the app's feed reads them (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_closed_schools_rules`;
// apps/schools/test_closed_schools_rules_export.py fails when the two differ.
package closedschools

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Doors is what a role is given on the archive, by the page's own gates.
type Doors struct {
	// Page opens the archive at all.
	Page bool `json:"page"`
	// Impact shows the year's closure impact.
	Impact bool `json:"impact"`
	// Profiles makes a school's name a link to its profile.
	Profiles bool `json:"profiles"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Doors              map[string]Doors `json:"doors"`
	ClosureTypes       [][2]string      `json:"closure_types"`
	ClosureReasons     [][2]string      `json:"closure_reasons"`
	OperatingStatuses  []string         `json:"operating_statuses"`
	MaxRows            int              `json:"max_rows"`
	PageSize           int              `json:"page_size"`
	QueryKeysNotPassed []string         `json:"query_keys_not_passed"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Doors) == 0 || len(r.ClosureTypes) == 0 ||
		len(r.ClosureReasons) == 0 || len(r.OperatingStatuses) == 0 || r.MaxRows <= 0 || r.PageSize <= 0 {
		panic(fmt.Sprintf("closedschools: the embedded rules are unreadable: %v", err))
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// display is Django's get_<field>_display: the choice's label, or the stored
// value when it is not one of the choices.
func display(choices [][2]string, value string) string {
	for _, c := range choices {
		if c[0] == value {
			return c[1]
		}
	}
	return value
}
