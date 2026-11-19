// Package home answers Home (GetHome), the phone's first tab and the app's
// start page, as the existing application builds it
// (apps.command_center.home_service.build_home, through
// apps.mobile_feed.views.HomeFeedView): the greeting, Today's overview, the
// reader's upcoming activities and Quick access.
//
// What depends only on the role — whether it may open Home, its title,
// whether it has a plan of its own, its Quick access — and Home's icons,
// figure labels and activity words are the existing ones, exported to
// rules.json by `manage.py export_home_rules`;
// apps/command_center/test_home_rules_export.py fails when the two differ.
// The figures and rows are read here, from the reader's own My Plan
// (myplan.ReadHomeCounts, myplan.ReadHomeUpcoming).
//
// It reads; it never writes. It hands on a partner (whose plan is their
// organisation's), an acting appointment and a role it has no rules for.
package home

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Shortcut is one of a role's Quick access pages.
type Shortcut struct {
	Label string `json:"label"`
	URL   string `json:"url"`
	Icon  string `json:"icon"`
}

// Role is what Home shows a role.
type Role struct {
	Home      bool       `json:"home"`
	Slug      string     `json:"slug"`
	Title     string     `json:"title"`
	HasPlan   bool       `json:"has_plan"`
	Shortcuts []Shortcut `json:"shortcuts"`
}

// Figure is a registered metric's words.
type Figure struct {
	Label       string `json:"label"`
	Description string `json:"description"`
}

// PriorityRow is one of the Priority actions the owner set for a role
// (home_priorities.SPECS): its words, icon, action, what it counts ("" for
// a page with nothing to count), the line under it then, and its link with
// FYMark where the year goes.
type PriorityRow struct {
	Key    string `json:"key"`
	Title  string `json:"title"`
	One    string `json:"one"`
	Icon   string `json:"icon"`
	Action string `json:"action"`
	Counts string `json:"counts"`
	Line   string `json:"line"`
	URL    string `json:"url"`
}

// Priorities are home_priorities': each role's rows in the owner's order.
type Priorities struct {
	Roles       map[string][]PriorityRow `json:"roles"`
	SchoolLists map[string]string        `json:"school_lists"`
	UnreadLine  string                   `json:"unread_line"`
	FYMark      string                   `json:"fy_mark"`
}

// Rules is rules.json.
type Rules struct {
	Roles         map[string]Role   `json:"roles"`
	Icons         map[string]string `json:"icons"`
	Figures       map[string]Figure `json:"figures"`
	UpcomingLimit int               `json:"upcoming_limit"`
	PriorityLimit int               `json:"priority_limit"`
	StatusLabels  map[string]string `json:"status_labels"`
	TypeLabels    map[string]string `json:"type_labels"`
	Priorities    Priorities        `json:"priorities"`
	QueueRows     QueueRows         `json:"queue_rows"`
}

// QueueRows are how a role without the owner's Priority actions words its
// To-Do rows on Home (home_service._todo_row, _group_row).
type QueueRows struct {
	CategoryIcons  map[string]string `json:"category_icons"`
	PriorityTones  map[string]string `json:"priority_tones"`
	PriorityLabels map[string]string `json:"priority_labels"`
	Tones          map[string]string `json:"tones"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("home: reading rules.json: %v", err))
	}
	return r
}

// label is a choice's words, or the value itself when it has none, as
// Django's get_FOO_display answers.
func label(choices map[string]string, value string) string {
	if words, ok := choices[value]; ok {
		return words
	}
	return value
}
