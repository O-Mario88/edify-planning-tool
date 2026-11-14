package iaframework

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// mapping is an activity_intervention_mapping row as the register reads it.
type mapping struct {
	id, item, status, intervention, mode, direction, country string
	reason, reviewNote, author, reviewedBy, submittedBy      string
	active, primary                                          bool
	version                                                  int
	min, expected, max                                       *int
	change                                                   *string
}

// window is framework._window.
func window(m *mapping) string {
	if m.min == nil && m.expected == nil && m.max == nil {
		return "No window"
	}
	part := func(p *int) string {
		if p == nil {
			return "—"
		}
		return strconv.Itoa(*p)
	}
	return part(m.min) + " / " + part(m.expected) + " / " + part(m.max) + " days"
}

// interventionText is framework._intervention_text.
func interventionText(m *mapping) string {
	switch {
	case m.reason != "":
		return "Not measured by a score"
	case m.intervention != "":
		return label(rules.InterventionLabels, m.intervention)
	case m.mode == "any_ssa_intervention":
		return "Planner selects"
	case m.mode == "inherit_from_source_activity":
		return "Inherited from the source activity"
	case m.mode == "ssa_completion_prerequisite":
		return "SSA completion (prerequisite)"
	}
	return "—"
}

func referenceDefault(m *mapping) bool {
	return m != nil && slices.Contains(rules.MachineAuthors, m.author) && m.status != "published"
}

// ruleState is framework.rule_state's words.
func ruleState(m *mapping) string {
	switch {
	case m == nil:
		return "Mapping required"
	case referenceDefault(m):
		return rules.ReferenceDefaultLabel
	case m.status == "draft" && m.reviewNote != "":
		return "Returned"
	}
	return label(rules.MappingStatuses, m.status)
}

func (s *Service) rulesTab(ctx context.Context, r reader, res *resolver, programme, status string) (tab, error) {
	type item struct{ id, name, programme string }
	rows, err := s.db.Query(ctx, `SELECT id, display_name, COALESCE(programme_category, '') FROM activity_catalogue_item
WHERE status = 'active' AND (requires_school OR cluster_delivery_allowed OR is_training_course) ORDER BY programme_category, display_name`)
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the catalogue: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (item, error) {
		var x item
		return x, row.Scan(&x.id, &x.name, &x.programme)
	})
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the catalogue: %w", err)
	}
	ids := make([]string, len(items))
	for i, x := range items {
		ids[i] = x.id
	}
	rows, err = s.db.Query(ctx, `
SELECT id, catalogue_item_id, status, COALESCE(intervention, ''), COALESCE(mapping_mode, ''), COALESCE(expected_direction, ''), COALESCE(country, ''),
  COALESCE(not_ssa_measured_reason, ''), COALESCE(review_note, ''), COALESCE(authored_by, ''), COALESCE(reviewed_by, ''), COALESCE(submitted_by, ''),
  active, is_primary, version, follow_up_min_days, follow_up_expected_days, follow_up_max_days, min_meaningful_change::text
FROM activity_intervention_mapping WHERE catalogue_item_id = ANY($1) AND (active OR status = ANY($2))
ORDER BY is_primary DESC, priority, version DESC`, ids, rules.PendingMappingStatuses)
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the rules: %w", err)
	}
	maps, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (mapping, error) {
		var m mapping
		return m, row.Scan(&m.id, &m.item, &m.status, &m.intervention, &m.mode, &m.direction, &m.country, &m.reason, &m.reviewNote,
			&m.author, &m.reviewedBy, &m.submittedBy, &m.active, &m.primary, &m.version, &m.min, &m.expected, &m.max, &m.change)
	})
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the rules: %w", err)
	}
	live, pending := map[string][]*mapping{}, map[string][]*mapping{}
	people := []string{}
	for i := range maps {
		m := &maps[i]
		if m.active {
			live[m.item] = append(live[m.item], m)
			people = append(people, m.reviewedBy)
		} else {
			pending[m.item] = append(pending[m.item], m)
			people = append(people, m.submittedBy)
		}
	}
	names, err := s.names(ctx, people)
	if err != nil {
		return tab{}, err
	}
	programmes := []string{}
	for _, x := range items {
		if !slices.Contains(programmes, x.programme) {
			programmes = append(programmes, x.programme)
		}
	}
	slices.Sort(programmes)
	t := tab{title: "Measurement rules",
		columns:    []string{"Programme", "Activity", "SSA domain", "Success looks like", "Follow-up window", "Meaningful change", "Scope", "Version", "Status", "Reviewed by"},
		emptyTitle: "No school-outcome activities match", emptyBody: "Clear the filters to see every activity with a school outcome.",
		notice:      "Only a published rule measures anything, and nobody publishes their own: save a draft, submit it with the reason for the change, and a second officer reviews it. Enrolments keep the rule stamped at their first verified delivery. Where no threshold is approved, any change counts, and readings under 120 days apart are not compared.",
		description: "Which SSA domain each school-facing, cluster or training activity is meant to move, how long before a follow-up means anything, and what counts as change."}
	options := [][2]string{}
	for _, p := range programmes {
		if p != "" {
			options = append(options, [2]string{p, p})
		}
	}
	if len(options) > 0 {
		t.filters = append(t.filters, choice("programme", "Programme", "Every programme", programme, options))
	}
	t.filters = append(t.filters, choice("status", "Status", "Every status", status, rules.RuleStatusFilters))
	for _, x := range items {
		if programme != "" && x.programme != programme {
			continue
		}
		var primary, waiting *mapping
		for _, m := range live[x.id] {
			if m.primary {
				primary = m
				break
			}
		}
		if len(pending[x.id]) > 0 {
			waiting = pending[x.id][0]
		}
		shown := primary
		state := ruleState(primary)
		key := "draft"
		switch {
		case primary == nil:
			key = "required"
		case referenceDefault(primary):
			key = "reference"
		case primary.status == "published":
			key = "published"
		}
		if waiting != nil {
			suffix := "v" + strconv.Itoa(waiting.version) + " " + strings.ToLower(ruleState(waiting))
			if primary != nil {
				state += " · " + suffix
			} else {
				state = suffix
			}
			key = "draft"
			if waiting.status == "in_review" {
				key = "in_review"
			}
			if shown == nil {
				shown = waiting
			}
		}
		if status != "" && key != status {
			continue
		}
		mayReview := false
		if waiting != nil && waiting.status == "in_review" {
			if mayReview, err = res.may(ctx, waiting.submittedBy, waiting.country); err != nil {
				return tab{}, err
			}
		}
		intervention, direction, win, threshold, scope, version := "—", "—", "—", "—", "—", "—"
		if shown != nil {
			intervention, win = interventionText(shown), window(shown)
			direction = label(rules.Directions, shown.direction)
			threshold = "Any change"
			if shown.change != nil {
				threshold = "±" + *shown.change
			}
			scope = shown.country
			if scope == "" {
				scope = "All countries"
			}
			version = "v" + strconv.Itoa(shown.version)
		}
		reviewed := "—"
		if primary != nil && primary.reviewedBy != "" {
			reviewed = names[primary.reviewedBy]
		}
		pairs := [][2]string{}
		if r.author {
			edit := "Edit rule"
			if state == "Mapping required" {
				edit = "Link intervention"
			}
			pairs = append(pairs, [2]string{edit, "/priorities/ssa-mapping/" + x.id + "/drawer"})
		}
		if mayReview {
			pairs = append(pairs, [2]string{"Review", "/priorities/ssa-mapping/rules/" + waiting.id + "/review"})
		}
		pairs = append(pairs, [2]string{"History", "/priorities/ssa-mapping/" + x.id + "/history"})
		prog := x.programme
		if prog == "" {
			prog = "Not categorised"
		}
		t.rows = append(t.rows, []*screensv1.PageCell{
			cell(prog), cell(x.name), cell(intervention), cell(direction), cell(win), cell(threshold),
			cell(scope), cell(version), cell(state), cell(reviewed), actions(pairs...),
		})
	}
	return t, nil
}
