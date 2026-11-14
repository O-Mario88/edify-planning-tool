// Package planningoversight is Planning Oversight (/team-planning-oversight/,
// apps.frontend.views.oversight_views.team_planning_oversight_view) and
// Country Oversight (/country-planning-oversight/,
// country_planning_oversight_view) as the app's feed (apps.mobile_feed)
// opens them, owned by Go piece by piece.
//
// Piece 1 is the pages' doors: every reader either page refuses gets the
// feed's "not available" from Go; every reader it opens for is handed to the
// existing application (served=false) until the lenses are built here.
//
// The doors are the existing ones, exported to rules.json by
// `manage.py export_planning_oversight_rules`;
// apps/planning/test_planning_oversight_rules_export.py fails when the two
// differ.
package planningoversight

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Page is one of the two pages as the feed knows it.
type Page struct {
	// Path is the page's URL as the app opens it.
	Path string `json:"path"`
	// FeedOpensPage: the page's URL name is in the feed's NATIVE_PAGES.
	FeedOpensPage bool `json:"feed_opens_page"`
}

// Door is whether a role reaches one page.
type Door struct {
	// Open: the feed's can_open_url lets the reader open the path.
	Open bool `json:"open"`
	// Page: the view's own page-permission decorator lets the reader in.
	Page bool `json:"page"`
}

// Rules is rules.json.
type Rules struct {
	// Pages by key: "team" and "country".
	Pages map[string]Page `json:"pages"`
	// Doors by role, then by page key.
	Doors map[string]map[string]Door `json:"doors"`
	// TeamPlan is what the Team Plan lens draws for a Programme Lead whose
	// team has nothing planned in the period.
	TeamPlan TeamPlan `json:"team_plan"`
}

// Tab is one tab or link of a strip.
type Tab struct {
	Key    string `json:"key"`
	Label  string `json:"label"`
	Href   string `json:"href"`
	Active bool   `json:"active"`
}

// KPI is one headline tile as _kpi_items builds it over no work.
type KPI struct {
	Label  string `json:"label"`
	Value  string `json:"value"`
	Helper string `json:"helper"`
	Tone   string `json:"tone"`
}

// TeamPlan is the Team Plan lens's vocabulary (oversight_views,
// oversight_service, flagged_schools).
type TeamPlan struct {
	// LeadRole is the role whose team lens this piece draws.
	LeadRole string `json:"lead_role"`
	// LensTabs is the lens strip the role holds, on the Team Plan.
	LensTabs []Tab `json:"lens_tabs"`
	// OwnerTabs are the two tabs before the officers: Whole team, My Work.
	OwnerTabs []Tab `json:"owner_tabs"`
	// ActivityTabs is the activity family strip.
	ActivityTabs []Tab `json:"activity_tabs"`
	// ZeroKPIs are the headline tiles over no work.
	ZeroKPIs []KPI `json:"zero_kpis"`
	// EvidenceLink: the role may open the Evidence Centre.
	EvidenceLink bool `json:"evidence_link"`
	// LiveActivityStatuses are the statuses build_items reads.
	LiveActivityStatuses []string `json:"live_activity_statuses"`
	// NotPlannedStatuses leave the month's planned schools (flagged).
	NotPlannedStatuses []string `json:"not_planned_statuses"`
	// FilterKeys are the advanced filters (read_filters).
	FilterKeys []string `json:"filter_keys"`
	// QueryKeysNotPassed are the keys the feed never passes to a page.
	QueryKeysNotPassed []string `json:"query_keys_not_passed"`
}

var rules = mustRules(rulesJSON)

func mustRules(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("planningoversight: rules.json: %v", err))
	}
	for _, key := range []string{teamKey, countryKey} {
		if r.Pages[key].Path == "" {
			panic("planningoversight: rules.json has no " + key + " page")
		}
	}
	if r.TeamPlan.LeadRole == "" || len(r.TeamPlan.OwnerTabs) != 2 || len(r.TeamPlan.ActivityTabs) == 0 || len(r.TeamPlan.LiveActivityStatuses) == 0 {
		panic("planningoversight: rules.json has no team plan")
	}
	return r
}
