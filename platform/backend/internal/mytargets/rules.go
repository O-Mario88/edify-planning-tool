// Package mytargets builds My Targets (/my-targets:
// apps.frontend.views.staff_views.my_targets_view over
// apps.targets.my_targets.MyTargetQueryService.get_page, as the existing feed
// reads partials/targets/my_body.html): the reader's agreed priorities for a
// month of the year, every period from that month to the full year, the
// cumulative trend, the roll-up, the areas to focus on, the strategic and
// Project priorities, the priority portfolio and the Core School tracker.
//
// It reads; it never writes. The existing page rebuilds the reader's
// achievement ledger first when it is marked stale; the target engine
// (internal/targets) works that rebuild out in memory instead, and the
// existing application stays the ledger's only writer. It hands on a
// team's or Project's allocation among the reader's own, a milestone with no
// metric definition, a list longer than one page, several assigned Project
// cards the feed reads apart, and any query it does not read. A reader
// without a People record (a partner's login) is drawn as the existing page
// draws them: without the strategic priorities, Projects, milestones or
// portfolio groups. The
// labels, statuses and doors are exported to rules.json by `manage.py
// export_my_targets_rules`; apps/targets/test_my_targets_rules_export.py
// fails when the two differ.
package mytargets

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles              []string             `json:"page_roles"`
	Opens                  map[string][]string  `json:"opens"`
	SSAHomes               map[string]link      `json:"ssa_homes"`
	Reader                 string               `json:"reader"`
	OnTrackBand            int                  `json:"on_track_band"`
	AtRiskBand             int                  `json:"at_risk_band"`
	NextActions            map[string][2]string `json:"next_actions"`
	AreaSources            map[string]source    `json:"area_sources"`
	CompletedStatuses      []string             `json:"completed_statuses"`
	ReturnedStatuses       []string             `json:"returned_statuses"`
	ReturnedForCorrection  []string             `json:"returned_for_correction_statuses"`
	LiveProjectStatuses    []string             `json:"live_project_statuses"`
	InterventionLabels     map[string]string    `json:"intervention_labels"`
	PriorityStatusLabels   map[string]string    `json:"priority_status_labels"`
	PDStatusLabels         map[string]string    `json:"pd_status_labels"`
	SSABands               [][3]any             `json:"ssa_bands"`
	OperatingStatuses      []string             `json:"operating_statuses"`
	SchoolFocusLabels      map[string]string    `json:"school_focus_labels"`
	ResponsibilityLabels   map[string]string    `json:"responsibility_labels"`
	ProjectCompletedStates []string             `json:"project_completed_states"`
	SchoolTypes            [][2]string          `json:"school_types"`
	// Strips are partials/_section_nav.html above the page, by role: the
	// workspace strip as the feed reads it, or nil.
	Strips map[string]*strip `json:"strips"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("mytargets: reading rules.json: %v", err))
	}
	if len(r.PageRoles) == 0 || len(r.NextActions) == 0 || len(r.AreaSources) == 0 || len(r.SSABands) == 0 ||
		len(r.OperatingStatuses) == 0 || r.Reader == "" || len(r.SchoolTypes) == 0 || len(r.Strips) == 0 {
		panic("mytargets: rules.json lacks the roles, the actions, the sources or the bands")
	}
	return r
}()

// strip is a role's workspace strip as the feed reads it (a linkTabs block).
type strip struct {
	Label   string `json:"label"`
	Scrolls bool   `json:"scrolls"`
	Tabs    []struct {
		Label  string `json:"label"`
		Href   string `json:"href"`
		Active bool   `json:"active"`
	} `json:"tabs"`
}

// block is the strip as a page block.
func (s *strip) block() *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Label: s.Label, Scrolls: s.Scrolls}
	for _, t := range s.Tabs {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

type link struct {
	Href  string `json:"href"`
	Label string `json:"label"`
}

// source is an area's AREA_SOURCES entry: the kind of record it credits and,
// for activities, their types.
type source struct {
	Kind  string
	Types []string
}

func (s *source) UnmarshalJSON(raw []byte) error {
	var pair []json.RawMessage
	if err := json.Unmarshal(raw, &pair); err != nil || len(pair) != 2 {
		return fmt.Errorf("mytargets: an area source is not a pair: %s", raw)
	}
	if err := json.Unmarshal(pair[0], &s.Kind); err != nil {
		return err
	}
	return json.Unmarshal(pair[1], &s.Types)
}

// opens is the template's |can_open for a linked page.
func opens(role, path string) bool { return slices.Contains(rules.Opens[path], role) }

// ssaBand is ssa_score_band's label and tone for a score.
func ssaBand(score float64) (string, string) {
	for _, b := range rules.SSABands {
		floor, _ := b[0].(float64)
		if score >= floor {
			label, _ := b[1].(string)
			tone, _ := b[2].(string)
			return label, tone
		}
	}
	return "", ""
}
