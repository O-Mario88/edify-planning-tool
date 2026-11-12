package schoolprofile

import (
	"context"
	"fmt"
	"math"
	"strconv"
	"strings"
)

// ── The SSA change rule (apps.ssa.change_rules) ─────────────────────────────

// changeRule is one published measurement rule: the smallest move that
// counts, and which way is better.
type changeRule struct {
	threshold *float64
	direction string
}

// ruleBook is change_rules.RuleBook: every published rule, the newest per
// intervention and country first.
type ruleBook map[[2]string]changeRule

func (s *Service) ruleBook(ctx context.Context) (ruleBook, error) {
	rows, err := s.db.Query(ctx, `
SELECT intervention, COALESCE(country, ''), COALESCE(expected_direction, ''), min_meaningful_change::float8
FROM activity_intervention_mapping
WHERE status = 'published' AND active AND intervention IS NOT NULL
ORDER BY effective_from DESC, version DESC, updated_at DESC`)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the SSA change rules: %w", err)
	}
	defer rows.Close()
	book := ruleBook{}
	for rows.Next() {
		var intervention, country, direction string
		var threshold *float64
		if err := rows.Scan(&intervention, &country, &direction, &threshold); err != nil {
			return nil, err
		}
		if intervention == "" {
			continue
		}
		key := [2]string{intervention, strings.TrimSpace(country)}
		if _, seen := book[key]; seen {
			continue
		}
		if threshold != nil {
			t := math.Abs(*threshold)
			threshold = &t
		}
		if direction == "" {
			direction = "improve"
		}
		book[key] = changeRule{threshold: threshold, direction: direction}
	}
	return book, rows.Err()
}

var fallbackRule = changeRule{direction: "improve"}

// rule is RuleBook.rule for the deployment (no country).
func (b ruleBook) rule(intervention string) changeRule { return b.ruleIn(intervention, "") }

// ruleIn is RuleBook.rule: the country's rule, else the deployment's, else
// any move.
func (b ruleBook) ruleIn(intervention, country string) changeRule {
	if country != "" {
		if r, ok := b[[2]string{intervention, country}]; ok {
			return r
		}
	}
	if r, ok := b[[2]string{intervention, ""}]; ok {
		return r
	}
	return fallbackRule
}

// schoolRuleIn is RuleBook.school_rule in a country, with the words it is
// shown in.
func (b ruleBook) schoolRuleIn(interventions []string, country string) (changeRule, string) {
	thresholds := []float64{}
	any := false
	for _, i := range interventions {
		r := b.ruleIn(i, country)
		if r.threshold != nil {
			any = true
			thresholds = append(thresholds, *r.threshold)
		} else {
			thresholds = append(thresholds, 0)
		}
	}
	if len(interventions) == 0 || !any {
		return fallbackRule, rules.Engine.FallbackRuleLabel
	}
	mean := pyRound(pySum(thresholds)/float64(len(thresholds)), 2)
	return changeRule{threshold: &mean, direction: "improve"},
		"±" + strconv.FormatFloat(mean, 'g', -1, 64) + " (mean of the approved domain rules)"
}

// schoolRule is RuleBook.school_rule for the deployment.
func (b ruleBook) schoolRule(interventions []string) changeRule {
	r, _ := b.schoolRuleIn(interventions, "")
	return r
}

// change is a verdict: the move and what the rule calls it.
type change struct {
	delta  *float64
	status string
}

func (c change) label() string { return label(rules.Engine.ChangeLabels, c.status) }
func (c change) tone() string  { return rules.Engine.ChangeTones[c.status] }

// between is change_rules.change_between for two readings with no dates.
func between(before, after float64, r changeRule) change {
	delta := pyRound(after-before, 2)
	c := change{delta: &delta}
	switch {
	case r.direction == "maintain_strong":
		c.status = "declined"
		if after >= rules.Engine.StrongScore {
			c.status = "maintained_strong"
		}
	case r.threshold != nil:
		switch {
		case delta >= *r.threshold:
			c.status = "improved"
		case delta <= -*r.threshold:
			c.status = "declined"
		default:
			c.status = "no_change"
		}
	case delta > 0:
		c.status = "improved"
	case delta < 0:
		c.status = "declined"
	default:
		c.status = "no_change"
	}
	return c
}

// overallChange is the engine's _change without an intervention: a school's
// (or a mean's) move, judged by the mean of every intervention's rule.
func (b ruleBook) overallChange(previous, current *float64) change {
	if previous == nil || current == nil {
		return change{status: "not_comparable"}
	}
	return between(0, pyRound(*current-*previous, 2), b.schoolRule(ssaInterventionOrder()))
}

// interventionChange is the engine's _change for one intervention.
func (b ruleBook) interventionChange(intervention string, previous, current *float64) change {
	if previous == nil || current == nil {
		return change{status: "not_comparable"}
	}
	return between(*previous, *current, b.rule(intervention))
}

// ── A school's score in a year (apps.ssa.year_comparison) ──────────────────

// yearScore is a school's score this year and the year before.
type yearScore struct{ current, previous *float64 }

// schoolYearScores is year_comparison.school_year_scores: each school's
// latest confirmed record of fy and of the year before; its average, else
// the mean of the scores it carries.
func (s *Service) schoolYearScores(ctx context.Context, schoolIDs []string, fy string) (map[string]yearScore, error) {
	years := []string{fy}
	if before := previousFY(fy); before != "" {
		years = append(years, before)
	}
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT ON (r.school_id, r.fy) r.id, r.school_id, r.fy, r.average_score
FROM ssa_record r
WHERE r.school_id = ANY($1) AND r.fy = ANY($2) AND r.deleted_at IS NULL AND r.verification_status = ANY($3)
ORDER BY r.school_id, r.fy, r.date_of_ssa DESC, r.created_at DESC, r.id DESC`, schoolIDs, years, rules.SSACurrentStatuses)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading SSA years: %w", err)
	}
	type latest struct {
		id, school, fy string
		average        *float64
	}
	records := []latest{}
	missing := []string{}
	for rows.Next() {
		var l latest
		if err := rows.Scan(&l.id, &l.school, &l.fy, &l.average); err != nil {
			rows.Close()
			return nil, err
		}
		records = append(records, l)
		if l.average == nil {
			missing = append(missing, l.id)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	carried := map[string][]*float64{}
	if len(missing) > 0 {
		rows, err := s.db.Query(ctx, `SELECT ssa_record_id, score FROM ssa_score WHERE ssa_record_id = ANY($1) AND score IS NOT NULL`, missing)
		if err != nil {
			return nil, fmt.Errorf("schoolprofile: reading SSA scores: %w", err)
		}
		for rows.Next() {
			var id string
			var score float64
			if err := rows.Scan(&id, &score); err != nil {
				rows.Close()
				return nil, err
			}
			v := score
			carried[id] = append(carried[id], &v)
		}
		rows.Close()
	}
	out := map[string]yearScore{}
	for _, l := range records {
		var value *float64
		if l.average != nil {
			v := pyRound(*l.average, 2)
			value = &v
		} else {
			value = pyMean(carried[l.id])
		}
		entry := out[l.school]
		if l.fy == fy {
			entry.current = value
		} else {
			entry.previous = value
		}
		out[l.school] = entry
	}
	return out, nil
}

// ssaInterventionOrder is SsaIntervention's values in their own order.
func ssaInterventionOrder() []string { return rules.Engine.InterventionOrder }

// twoPlaces is |floatformat:2.
func twoPlaces(v float64) string { return floatformat(v, 2) }

// signedTwoPlaces is a change as the page writes it: "+0.40", "-0.20".
func signedTwoPlaces(v float64) string {
	if v > 0 {
		return "+" + twoPlaces(v)
	}
	return twoPlaces(v)
}

func itoa(n int) string { return strconv.Itoa(n) }
