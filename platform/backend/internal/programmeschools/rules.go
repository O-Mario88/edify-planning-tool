// Package programmeschools is the Programme Schools page
// (/programme-schools): Core Trained, Core Graduate and Champion schools in
// one list, each with what it has taken of its year, as the existing page
// draws it (apps.frontend.views.school_views.programme_schools_view,
// apps.schools.programme_schools and pages/schools/programme_schools.html)
// and the app's feed reads it (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_programme_schools_rules`;
// apps/schools/test_programme_schools_rules_export.py fails when the two
// differ. The visit rule a row reads is the school profile's
// (internal/visitgate, schoolprofile.GateRules).
package programmeschools

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Doors is what a role is given on the page, by the page's own gates.
type Doors struct {
	// Page opens the page at all.
	Page bool `json:"page"`
	// Schedule offers Schedule on a row, where anyone else is offered View.
	Schedule bool `json:"schedule"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Doors map[string]Doors `json:"doors"`
	// SchoolTypes are the three programme types and their labels, in the
	// page's order.
	SchoolTypes        [][2]string `json:"school_types"`
	OperatingStatuses  []string    `json:"operating_statuses"`
	MaxRows            int         `json:"max_rows"`
	PageSize           int         `json:"page_size"`
	QueryKeysNotPassed []string    `json:"query_keys_not_passed"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Doors) == 0 || len(r.SchoolTypes) == 0 ||
		len(r.OperatingStatuses) == 0 || r.MaxRows <= 0 || r.PageSize <= 0 {
		panic(fmt.Sprintf("programmeschools: the embedded rules are unreadable: %v", err))
	}
	return r
}

// typeValues are the programme types' stored values.
func typeValues() []string {
	out := make([]string, len(rules.SchoolTypes))
	for i, t := range rules.SchoolTypes {
		out[i] = t[0]
	}
	return out
}

func isProgrammeType(value string) bool { return slices.Contains(typeValues(), value) }
