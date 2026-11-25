// Package actionsweep is the hourly school_action_sweep job
// (apps.planning.action_service.resolve_due_actions, then
// mark_overdue_actions): every active delegated action whose condition has
// cleared is closed by the system, and every one past its due date is
// flagged overdue, each with the notices the existing job sends.
package actionsweep

import (
	_ "embed"
	"encoding/json"
	"slices"
)

// The rules are exported by `python manage.py export_action_sweep_rules`
// and kept in step by apps/planning/test_action_sweep_rules_export.py.
//
//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	SystemVerifiable         []string          `json:"system_verifiable"`
	OversightRiskKeys        []string          `json:"oversight_risk_keys"`
	PartnerOversightRiskKeys []string          `json:"partner_oversight_risk_keys"`
	CoreOversightRiskKeys    []string          `json:"core_oversight_risk_keys"`
	PlanningGapKeys          []string          `json:"planning_gap_keys"`
	SchoolGapFigure          map[string]string `json:"school_gap_figure"`
	ActiveStates             []string          `json:"active_states"`
	OverdueFromStates        []string          `json:"overdue_from_states"`
	ResolvedState            string            `json:"resolved_state"`
	OverdueState             string            `json:"overdue_state"`
	OversightKeyPrefixes     []string          `json:"oversight_key_prefixes"`
	IAVerifiedStatuses       []string          `json:"ia_verified_statuses"`
	VisitTypes               []string          `json:"visit_types"`
	TrainingTypes            []string          `json:"training_types"`
	SSABands                 [][2]any          `json:"ssa_bands"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic("actionsweep: rules.json: " + err.Error())
	}
	if len(r.SystemVerifiable) == 0 || len(r.ActiveStates) == 0 || len(r.SSABands) == 0 {
		panic("actionsweep: rules.json is incomplete")
	}
	return r
}()

func in(list []string, v string) bool { return slices.Contains(list, v) }

// band is ssa_score_band's label for a score.
func band(score float64) string {
	for _, b := range rules.SSABands {
		floor, _ := b[0].(float64)
		if score >= floor {
			label, _ := b[1].(string)
			return label
		}
	}
	return ""
}
