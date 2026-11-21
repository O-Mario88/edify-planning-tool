// Package navigation answers GetNavigation, the bottom bar and the full menu
// the app and the web app draw for the reader's role, as the existing
// application builds them (apps.core.navigation.build_sidebar_for_user and
// build_mobile_nav_for_user, through apps.mobile_feed.views.NavigationFeedView).
//
// The menus are the existing ones, exported to rules.json by
// `manage.py export_navigation_rules` for every role, and once more for a
// partner's team member; apps/core/test_navigation_rules_export.py fails when
// the two differ. Go decides which of them the reader is given.
package navigation

import (
	_ "embed"
	"encoding/json"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// Item is one destination: its words, path, icon (a place in Rules.Icons),
// page key and whether the app draws it from its components.
type Item struct {
	Label   string `json:"label"`
	URL     string `json:"url"`
	Icon    int    `json:"icon"`
	PageKey string `json:"page_key"`
	Native  bool   `json:"native"`
}

// Section is one group of the menu.
type Section struct {
	Label string `json:"label"`
	Items []Item `json:"items"`
}

// Menu is one reader's navigation: the bar and the menu.
type Menu struct {
	Bottom   []Item    `json:"bottom"`
	Sections []Section `json:"sections"`
}

// Rules are every role's navigation.
type Rules struct {
	// Roles is the navigation of a login in its own role, by role.
	Roles map[string]Menu `json:"roles"`
	// TeamMembers is a partner team member's navigation, by partner role.
	TeamMembers map[string]Menu `json:"team_members"`
	// Acting is the navigation of a staff member working in an acting
	// capacity, by acting policy key (acting_pl, acting_cd).
	Acting map[string]Menu `json:"acting"`
	// PartnerTeam names the roles whose logins may be team members.
	PartnerTeam decisionlog.PartnerTeam `json:"partner_team"`
	// Icons are the SVG drawings the items name by place.
	Icons []string `json:"icons"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || len(r.Icons) == 0 ||
		len(r.TeamMembers) != len(r.PartnerTeam.Roles) || len(r.Acting) == 0 {
		panic(fmt.Sprintf("navigation: the embedded rules are unreadable: %v", err))
	}
	for _, menus := range []map[string]Menu{r.Roles, r.TeamMembers, r.Acting} {
		for role, menu := range menus {
			for _, item := range menu.items() {
				if item.Icon < 0 || item.Icon >= len(r.Icons) {
					panic(fmt.Sprintf("navigation: %s's %q names an icon that is not there", role, item.PageKey))
				}
			}
		}
	}
	return r
}

func (m Menu) items() []Item {
	out := append([]Item{}, m.Bottom...)
	for _, s := range m.Sections {
		out = append(out, s.Items...)
	}
	return out
}
