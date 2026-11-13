// Package oversightportfolio is the portfolio lens of Planning Oversight
// (/team-planning-oversight/?view=portfolio: oversight_views.
// team_planning_oversight_view's portfolio branch, _portfolio_context,
// _portfolio_kpis, partials/oversight/portfolio_workspace.html and
// apps.planning.portfolio_service.country_portfolio) as the app's feed
// (apps.mobile_feed) reads it: every school in the reader's analytics scope,
// under the Programme Lead and the CCEO who hold it, and what is planned on
// each.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_oversight_portfolio_rules`;
// apps/planning/test_oversight_portfolio_rules_export.py fails when the two
// differ. The words the template writes are written here.
package oversightportfolio

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"regexp"
)

//go:embed rules.json
var rulesJSON []byte

// LensTab is one link of the oversight lens strip.
type LensTab struct {
	Label  string `json:"label"`
	Href   string `json:"href"`
	Active bool   `json:"active"`
}

// Doors is what one role reaches.
type Doors struct {
	// Page: the view's require_any_page_permission lets the role in.
	Page bool `json:"page"`
	// FeedOpens: the feed's can_open_url opens the path for the role.
	FeedOpens bool `json:"feed_opens"`
	// Portfolio is the lens itself (team_oversight_lenses' "portfolio").
	Portfolio bool `json:"portfolio"`
	// CountryReader is is_country_reader for the role (a superuser is one
	// whatever the role).
	CountryReader bool `json:"country_reader"`
	// The strip above the lens, for a reader of the country and for a team.
	LensTabsCountry []LensTab `json:"lens_tabs_country"`
	LensTabsTeam    []LensTab `json:"lens_tabs_team"`
}

// Rules is rules.json.
type Rules struct {
	Doors              map[string]Doors `json:"doors"`
	VisitTypes         []string         `json:"visit_types"`
	TrainingTypes      []string         `json:"training_types"`
	DeadStatuses       []string         `json:"dead_statuses"`
	OperatingStatuses  []string         `json:"operating_statuses"`
	ProgramLeadRole    string           `json:"program_lead_role"`
	NoLeadKey          string           `json:"no_lead_key"`
	NoLeadLabel        string           `json:"no_lead_label"`
	UnassignedKey      string           `json:"unassigned_key"`
	UnassignedLabel    string           `json:"unassigned_label"`
	PageSize           int              `json:"page_size"`
	QueryKeyPattern    string           `json:"query_key_pattern"`
	QueryKeysNotPassed []string         `json:"query_keys_not_passed"`
	MaxQueryValue      int              `json:"max_query_value"`
}

var rules = mustRules(rulesJSON)

var queryKey = regexp.MustCompile(rules.QueryKeyPattern)

func mustRules(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("oversightportfolio: rules.json: %v", err))
	}
	if len(r.Doors) == 0 || len(r.VisitTypes) == 0 || len(r.TrainingTypes) == 0 ||
		len(r.OperatingStatuses) == 0 || r.PageSize < 1 || r.ProgramLeadRole == "" {
		panic("oversightportfolio: rules.json is incomplete")
	}
	return r
}
