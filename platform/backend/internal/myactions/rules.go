// Package myactions is My Actions (/actions/mine): the school actions handed
// to the reader, their tabs and counts, and the queue's pages, as the
// existing page draws them (apps.frontend.views.action_views.
// my_actions_view, apps.planning.action_workspace.actions_received,
// pages/actions/workspace.html and partials/actions/table.html) and the
// app's feed reads them (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_my_actions_rules`;
// apps/planning/test_my_actions_rules_export.py fails when the two differ.
package myactions

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// StripTab is one link of a workspace strip, as the feed reads it.
type StripTab struct {
	Label  string `json:"label"`
	Href   string `json:"href"`
	Active bool   `json:"active"`
}

// Strip is the workspace strip the page shows a role, as the feed reads it.
type Strip struct {
	Tabs    []StripTab `json:"tabs"`
	Label   string     `json:"label"`
	Scrolls bool       `json:"scrolls"`
}

// Role is what a role is given on the page.
type Role struct {
	Page  bool   `json:"page"`
	Strip *Strip `json:"strip"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles              map[string]Role         `json:"roles"`
	Tabs               [][2]string             `json:"tabs"`
	IssueLabels        map[string]string       `json:"issue_labels"`
	StateTones         map[string][2]string    `json:"state_tones"`
	ActiveStates       []string                `json:"active_states"`
	OverdueState       string                  `json:"overdue_state"`
	EscalatedState     string                  `json:"escalated_state"`
	ResolvedState      string                  `json:"resolved_state"`
	RowLimit           int                     `json:"row_limit"`
	PageSize           int                     `json:"page_size"`
	QueryKeysNotPassed []string                `json:"query_keys_not_passed"`
	PartnerTeamMembers decisionlog.PartnerTeam `json:"partner_team_members"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || len(r.Tabs) == 0 || len(r.IssueLabels) == 0 ||
		len(r.StateTones) == 0 || len(r.ActiveStates) == 0 || r.OverdueState == "" || r.EscalatedState == "" ||
		r.ResolvedState == "" || r.RowLimit <= 0 || r.PageSize <= 0 {
		panic(fmt.Sprintf("myactions: the embedded rules are unreadable: %v", err))
	}
	return r
}

func active(state string) bool { return slices.Contains(rules.ActiveStates, state) }
