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
	return r
}
