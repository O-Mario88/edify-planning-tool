// Package mytargets builds My Targets (/my-targets:
// apps.frontend.views.staff_views.my_targets_view over
// apps.targets.my_targets.MyTargetQueryService.get_page, as the existing feed
// reads partials/targets/my_body.html): the reader's agreed priorities for a
// month of the year, every period from that month to the full year, the
// cumulative trend, the roll-up, the areas to focus on, the strategic and
// Project priorities, the priority portfolio and the Core School tracker.
//
// It reads; it never writes. The existing page rebuilds the reader's
// achievement ledger first; the target engine (internal/targets) hands the
// page on whenever that rebuild would change anything. It also hands on a
// year with approved milestone allocations, a strategic priority past
// definition, an assigned Project, a role shown a section strip, a reader
// without a People record, a partner, and any query it does not read. The
// labels, statuses and doors are exported to rules.json by `manage.py
// export_my_targets_rules`; apps/targets/test_my_targets_rules_export.py
// fails when the two differ.
package mytargets

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
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
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("mytargets: reading rules.json: %v", err))
	}
	if len(r.PageRoles) == 0 || len(r.NextActions) == 0 || len(r.AreaSources) == 0 || len(r.SSABands) == 0 ||
		len(r.OperatingStatuses) == 0 || r.Reader == "" {
		panic("mytargets: rules.json lacks the roles, the actions, the sources or the bands")
	}
	return r
}()

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
