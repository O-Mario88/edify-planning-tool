// Package partnercapabilities is apps.partners.capabilities: the interventions
// a partner organisation can be recorded as delivering, and the catalogue
// activities a partner may be given under each.
package partnercapabilities

import (
	"context"
	"fmt"
	"slices"

	"github.com/jackc/pgx/v5"
)

const (
	loanKey   = "loan"
	loanLabel = "Loan"
	anyKey    = "group:any"
	anyLabel  = "Any SSA intervention"
	otherKey  = "group:unmapped"
	otherName = "Not mapped to an intervention"
)

// nullInterventionModes is NULL_INTERVENTION_MODES: mappings that name no
// single intervention, whatever their intervention column holds.
var nullInterventionModes = []string{"ssa_completion_prerequisite", "administrative", "inherit_from_source_activity", "any_ssa_intervention"}

// Activity is one catalogue item a partner may deliver.
type Activity struct {
	Code, Name string
}

// Group is an intervention, or one of the groups that is not one, with the
// activities under it.
type Group struct {
	Key, Label string
	Activities []Activity
}

type mapping struct {
	code, intervention, mode string
}

// Querier is the read this package needs from a pool or transaction.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
}

// Groups is intervention_activity_options, in the order interventions lists
// them, then Loan, then the two groups that are not interventions when they
// hold anything.
func Groups(ctx context.Context, q Querier, interventions [][2]string) ([]Group, error) {
	rows, err := q.Query(ctx, `
SELECT stable_code, display_name FROM activity_catalogue_item
 WHERE status = 'active' AND partner_delivery_allowed ORDER BY display_name`)
	if err != nil {
		return nil, fmt.Errorf("partnercapabilities: reading the catalogue: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Activity, error) {
		var item Activity
		err := row.Scan(&item.Code, &item.Name)
		return item, err
	})
	if err != nil {
		return nil, fmt.Errorf("partnercapabilities: reading a catalogue item: %w", err)
	}
	if len(items) == 0 {
		return buildGroups(interventions, nil, nil), nil
	}
	codes := make([]string, len(items))
	for i, item := range items {
		codes[i] = item.Code
	}
	rows, err = q.Query(ctx, `
SELECT c.stable_code, COALESCE(m.intervention, ''), m.mapping_mode
  FROM activity_intervention_mapping m JOIN activity_catalogue_item c ON c.id = m.catalogue_item_id
 WHERE m.active AND c.stable_code = ANY($1)
 ORDER BY m.priority, c.display_name`, codes)
	if err != nil {
		return nil, fmt.Errorf("partnercapabilities: reading the mappings: %w", err)
	}
	mappings, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (mapping, error) {
		var m mapping
		err := row.Scan(&m.code, &m.intervention, &m.mode)
		return m, err
	})
	if err != nil {
		return nil, fmt.Errorf("partnercapabilities: reading a mapping: %w", err)
	}
	return buildGroups(interventions, items, mappings), nil
}

// buildGroups files each activity under what its mappings say. An activity
// no mapping names is still drawn: one nobody can tick is one no partner can
// be recorded as doing.
func buildGroups(interventions [][2]string, items []Activity, mappings []mapping) []Group {
	names := make(map[string]string, len(items))
	for _, item := range items {
		names[item.Code] = item.Name
	}
	under := map[string][]Activity{}
	mapped := map[string]bool{}
	for _, m := range mappings {
		key := m.intervention
		if key == "" || slices.Contains(nullInterventionModes, m.mode) {
			key = anyKey
		}
		held := Activity{Code: m.code, Name: names[m.code]}
		if !slices.Contains(under[key], held) {
			under[key] = append(under[key], held)
		}
		mapped[m.code] = true
	}
	for _, item := range items {
		if !mapped[item.Code] {
			under[otherKey] = append(under[otherKey], item)
		}
	}
	groups := make([]Group, 0, len(interventions)+3)
	for _, intervention := range interventions {
		groups = append(groups, Group{Key: intervention[0], Label: intervention[1], Activities: under[intervention[0]]})
	}
	groups = append(groups, Group{Key: loanKey, Label: loanLabel})
	for _, extra := range [][2]string{{anyKey, anyLabel}, {otherKey, otherName}} {
		if len(under[extra[0]]) > 0 {
			groups = append(groups, Group{Key: extra[0], Label: extra[1], Activities: under[extra[0]]})
		}
	}
	return groups
}
