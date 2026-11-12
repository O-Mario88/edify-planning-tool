// Package decisionlog is the Decision Log (/decision-log): the decisions a
// person may read from the tamper-evident audit chain, their lookback
// window, the decision groups and the table's pages, as the existing page
// draws them (apps.frontend.views.decision_views.decision_log_view,
// apps.audit.decision_log_service and partials/analytics/panels/
// decision_log.html inside pages/analytics/workspace.html) and the app's
// feed reads them (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_decision_log_rules`;
// apps/audit/test_decision_log_rules_export.py fails when the two differ.
package decisionlog

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Reach is whose decisions a role reads: "global" (every one), "country"
// (those taken by people in the reader's country) or "own".
type Reach string

const (
	reachGlobal  Reach = "global"
	reachCountry Reach = "country"
)

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
	// Page opens the Decision Log at all.
	Page       bool   `json:"page"`
	Reach      Reach  `json:"reach"`
	ScopeLabel string `json:"scope_label"`
	// Strip is the workspace strip above the page, or nil.
	Strip *Strip `json:"strip"`
}

// Group is a decision group and the audit actions it holds.
type Group struct {
	Name    string
	Actions []string
}

// UnmarshalJSON reads the exported [name, actions] pair.
func (g *Group) UnmarshalJSON(raw []byte) error {
	pair := []json.RawMessage{}
	if err := json.Unmarshal(raw, &pair); err != nil || len(pair) != 2 {
		return fmt.Errorf("a group is [name, actions]: %s", raw)
	}
	if err := json.Unmarshal(pair[0], &g.Name); err != nil {
		return err
	}
	return json.Unmarshal(pair[1], &g.Actions)
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles              map[string]Role   `json:"roles"`
	Groups             []Group           `json:"groups"`
	Labels             map[string]string `json:"labels"`
	DetailKeys         []string          `json:"detail_keys"`
	DayOptions         []int             `json:"day_options"`
	DefaultDays        int               `json:"default_days"`
	MaxDays            int               `json:"max_days"`
	RowLimit           int               `json:"row_limit"`
	PageSize           int               `json:"page_size"`
	QueryKeysNotPassed []string          `json:"query_keys_not_passed"`
	PartnerTeamMembers PartnerTeam       `json:"partner_team_members"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || len(r.Groups) == 0 ||
		len(r.Labels) == 0 || len(r.DetailKeys) == 0 || len(r.DayOptions) == 0 || r.DefaultDays <= 0 ||
		r.MaxDays <= 0 || r.RowLimit <= 0 || r.PageSize <= 0 {
		panic(fmt.Sprintf("decisionlog: the embedded rules are unreadable: %v", err))
	}
	return r
}

// allActions is ALL_DECISION_ACTIONS: every group's actions, in order.
func allActions() []string {
	out := []string{}
	for _, g := range rules.Groups {
		out = append(out, g.Actions...)
	}
	return out
}

// groupActions is the actions of the named group, and whether it is one.
func groupActions(name string) ([]string, bool) {
	for _, g := range rules.Groups {
		if g.Name == name {
			return g.Actions, true
		}
	}
	return nil, false
}

// groupFor is _group_for: the group an action belongs to, else "Other".
func groupFor(action string) string {
	for _, g := range rules.Groups {
		if slices.Contains(g.Actions, action) {
			return g.Name
		}
	}
	return "Other"
}
