package iapages

// The portfolio a report freezes (ia_workflow.portfolio_change): paired
// confirmed SSAs across every operating school in the author's scope, the
// year before against the report's year, judged by the published IA
// measurement rules (apps.ssa.change_rules).

import (
	"context"
	"fmt"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	changeImproved         = "improved"
	changeDeclined         = "declined"
	changeNoChange         = "no_change"
	changeMaintainedStrong = "maintained_strong"
	strongScore            = 8.0
	fallbackRuleLabel      = "Any change (no approved threshold)"
)

// measurementRule is change_rules' rule dict.
type measurementRule struct {
	threshold *float64
	direction string
	label     string
	governed  bool // a published mapping, not the fallback
}

var fallbackMeasurementRule = measurementRule{direction: "improve", label: fallbackRuleLabel}

type measurementBook map[[2]string]measurementRule

func pyRound2(x float64) float64 { return math.RoundToEven(x*100) / 100 }

func pyG(x float64) string { return strconv.FormatFloat(x, 'g', -1, 64) }

// readMeasurementBook is RuleBook(): every published, active rule naming an
// intervention, the first read (newest first) for each intervention and
// country.
func (s *Service) readMeasurementBook(ctx context.Context) (measurementBook, error) {
	rows, err := s.db.Query(ctx, `SELECT intervention, COALESCE(country, ''), version, COALESCE(expected_direction, ''),
  min_meaningful_change::float8 FROM activity_intervention_mapping
WHERE status = 'published' AND active AND intervention IS NOT NULL
ORDER BY effective_from DESC, version DESC, updated_at DESC`)
	if err != nil {
		return nil, fmt.Errorf("iapages: the measurement rules: %w", err)
	}
	defer rows.Close()
	book := measurementBook{}
	for rows.Next() {
		var intervention, country, direction string
		var version int
		var threshold *float64
		if err := rows.Scan(&intervention, &country, &version, &direction, &threshold); err != nil {
			return nil, fmt.Errorf("iapages: a measurement rule: %w", err)
		}
		if intervention == "" {
			continue
		}
		key := [2]string{intervention, strings.TrimSpace(country)}
		if _, seen := book[key]; seen {
			continue
		}
		rule := measurementRule{direction: direction, governed: true}
		if rule.direction == "" {
			rule.direction = "improve"
		}
		where := country
		if where == "" {
			where = "all countries"
		}
		if threshold != nil {
			t := math.Abs(*threshold)
			rule.threshold = &t
			rule.label = fmt.Sprintf("±%s (approved rule v%d, %s)", pyG(t), version, where)
		} else {
			rule.label = fmt.Sprintf("Any change (rule v%d, %s, no threshold)", version, where)
		}
		book[key] = rule
	}
	return book, rows.Err()
}

func (b measurementBook) rule(intervention, country string) measurementRule {
	country = strings.TrimSpace(country)
	if country != "" {
		if r, ok := b[[2]string{intervention, country}]; ok {
			return r
		}
	}
	if r, ok := b[[2]string{intervention, ""}]; ok {
		return r
	}
	return fallbackMeasurementRule
}

func (b measurementBook) schoolRule(interventions []string, country string) measurementRule {
	thresholds, any := []float64{}, false
	n := 0
	for _, i := range interventions {
		if i == "" {
			continue
		}
		n++
		r := b.rule(i, country)
		if r.threshold != nil {
			any = true
			thresholds = append(thresholds, *r.threshold)
		} else {
			thresholds = append(thresholds, 0)
		}
	}
	if n == 0 || !any {
		return fallbackMeasurementRule
	}
	sum := 0.0
	for _, t := range thresholds {
		sum += t
	}
	mean := pyRound2(sum / float64(len(thresholds)))
	return measurementRule{threshold: &mean, direction: "improve", label: fmt.Sprintf("±%s (mean of the approved domain rules)", pyG(mean))}
}

// ruleLabelFor is change_rules.rule_label_for over every domain.
func (b measurementBook) ruleLabelFor() string {
	governed := 0
	for _, i := range rules.Dashboard.Outcomes.Interventions {
		if b.rule(i[0], "").governed {
			governed++
		}
	}
	if governed == 0 {
		return fallbackRuleLabel
	}
	return fmt.Sprintf("Approved IA rules for %d of %d SSA domains; any change elsewhere", governed, len(rules.Dashboard.Outcomes.Interventions))
}

// changeBetween is change_rules.change_between for two present readings.
func changeBetween(before, after float64, rule measurementRule) (string, float64) {
	delta := pyRound2(after - before)
	if rule.direction == "maintain_strong" {
		if after >= strongScore {
			return changeMaintainedStrong, delta
		}
		return changeDeclined, delta
	}
	if rule.threshold != nil {
		switch {
		case delta >= *rule.threshold:
			return changeImproved, delta
		case delta <= -*rule.threshold:
			return changeDeclined, delta
		}
		return changeNoChange, delta
	}
	switch {
	case delta > 0:
		return changeImproved, delta
	case delta < 0:
		return changeDeclined, delta
	}
	return changeNoChange, delta
}

// classifiedPair is one row of classify_pairs.
type classifiedPair struct {
	school, intervention string
	delta                float64
	classification       string
	ruleLabel            string
	start, end           time.Time
}

type schoolVerdict struct {
	meanDelta      float64
	classification string
}

// portfolioChange is ia_workflow.portfolio_change for the year fy.
func (s *Service) portfolioChange(ctx context.Context, scope schooldirectory.Scope, fy string) (map[string]any, error) {
	n, _ := strconv.Atoi(fy)
	prev := strconv.Itoa(n - 1)
	o := rules.Dashboard.Outcomes
	base := map[string]any{
		"fy": fy, "prev_fy": prev, "schools_in_scope": 0, "measured": 0, "improved": 0, "declined": 0, "no_change": 0,
		"improved_pct": nil, "declined_pct": nil, "median_interval_days": nil, "rows": []any{},
		"rule_label": o.FallbackLabel, "rule_sentence": o.RuleSentence, "grade": evidenceGrade(0, nil, nil),
		"limitation": o.PortfolioLimitation,
	}
	if scope.SummaryOnly {
		return base, nil
	}
	schools, args := activeSchools(scope)
	rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(r.country, '') FROM school s LEFT JOIN region r ON r.id = s.region_id WHERE `+schools, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: the portfolio's schools: %w", err)
	}
	countries := map[string]string{}
	ids := []string{}
	for rows.Next() {
		var id, country string
		if err := rows.Scan(&id, &country); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: a portfolio school: %w", err)
		}
		countries[id] = country
		ids = append(ids, id)
	}
	rows.Close()
	base["schools_in_scope"] = len(countries)
	if len(countries) == 0 {
		return base, nil
	}
	book, err := s.readMeasurementBook(ctx)
	if err != nil {
		return nil, err
	}
	base["rule_label"] = book.ruleLabelFor()
	pairs, err := s.classifiedPairs(ctx, ids, fy, prev, book, countries)
	if err != nil {
		return nil, err
	}
	groups, err := s.areaGroups(ctx)
	if err != nil {
		return nil, err
	}
	if len(pairs) == 0 {
		list := []any{}
		for _, g := range groups {
			list = append(list, map[string]any{"name": g.name, "is_area": true, "n": 0, "domains": anyStrings(g.domains)})
		}
		base["rows"] = list
		return base, nil
	}
	verdicts := schoolVerdicts(pairs, book, countries)
	byClass := map[string]int{}
	for _, v := range verdicts {
		byClass[v.classification]++
	}
	intervals := map[string]float64{}
	for _, p := range pairs {
		intervals[p.school] = float64(int(p.end.Sub(p.start).Hours() / 24))
	}
	measured := len(verdicts)
	base["measured"], base["improved"], base["declined"], base["no_change"] = measured, byClass[changeImproved], byClass[changeDeclined], byClass[changeNoChange]
	base["improved_pct"], base["declined_pct"] = intOrNil(share(byClass[changeImproved], measured)), intOrNil(share(byClass[changeDeclined], measured))
	if len(intervals) > 0 {
		values := make([]float64, 0, len(intervals))
		for _, v := range intervals {
			values = append(values, v)
		}
		base["median_interval_days"] = int(math.RoundToEven(rawMedian(values)))
	}
	one, missing := 1.0, 1-float64(measured)/float64(len(countries))
	base["grade"] = evidenceGrade(measured, &one, &missing)
	out := []any{}
	for _, g := range groups {
		area := []classifiedPair{}
		for _, p := range pairs {
			if slices.Contains(g.domains, p.intervention) {
				area = append(area, p)
			}
		}
		areaVerdicts := verdicts
		if len(area) != len(pairs) {
			areaVerdicts = schoolVerdicts(area, book, countries)
		}
		row := changeRow(g.name, area, areaVerdicts, len(countries), true)
		row["domains"] = anyStrings(g.domains)
		out = append(out, row)
		for _, code := range g.domains {
			domain := []classifiedPair{}
			for _, p := range area {
				if p.intervention == code {
					domain = append(domain, p)
				}
			}
			label := code
			for _, iv := range o.Interventions {
				if iv[0] == code {
					label = iv[1]
				}
			}
			out = append(out, changeRow(label, domain, nil, len(countries), false))
		}
	}
	base["rows"] = out
	return base, nil
}

func anyStrings(in []string) []any {
	out := make([]any, len(in))
	for i, v := range in {
		out[i] = v
	}
	return out
}

// rawMedian is statistics.median.
func rawMedian(values []float64) float64 {
	v := slices.Clone(values)
	sort.Float64s(v)
	n := len(v)
	if n%2 == 1 {
		return v[n/2]
	}
	return (v[n/2-1] + v[n/2]) / 2
}

// classifiedPairs is improvement_rows then classify_pairs.
func (s *Service) classifiedPairs(ctx context.Context, ids []string, fy, prev string, book measurementBook, countries map[string]string) ([]classifiedPair, error) {
	type reading struct {
		record string
		on     time.Time
	}
	latest := func(schools []string, year string) (map[string]reading, []string, error) {
		rows, err := s.db.Query(ctx, `SELECT DISTINCT ON (school_id) school_id, id, (date_of_ssa AT TIME ZONE 'UTC')::date
FROM ssa_record WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL AND verification_status = 'confirmed'
ORDER BY school_id, date_of_ssa DESC, created_at DESC`, schools, year)
		if err != nil {
			return nil, nil, fmt.Errorf("iapages: the latest confirmed SSAs: %w", err)
		}
		defer rows.Close()
		out, order := map[string]reading{}, []string{}
		for rows.Next() {
			var school string
			var r reading
			if err := rows.Scan(&school, &r.record, &r.on); err != nil {
				return nil, nil, fmt.Errorf("iapages: a confirmed SSA: %w", err)
			}
			out[school] = r
			order = append(order, school)
		}
		return out, order, rows.Err()
	}
	curr, order, err := latest(ids, fy)
	if err != nil {
		return nil, err
	}
	before, _, err := latest(order, prev)
	if err != nil {
		return nil, err
	}
	paired := []string{}
	records := []string{}
	for _, school := range order {
		if _, ok := before[school]; ok {
			paired = append(paired, school)
			records = append(records, curr[school].record, before[school].record)
		}
	}
	if len(paired) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT ssa_record_id, intervention, score::float8 FROM ssa_score WHERE ssa_record_id = ANY($1)`, records)
	if err != nil {
		return nil, fmt.Errorf("iapages: the SSA scores: %w", err)
	}
	scores := map[string]map[string]float64{}
	for rows.Next() {
		var record, intervention string
		var score float64
		if err := rows.Scan(&record, &intervention, &score); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: an SSA score: %w", err)
		}
		if scores[record] == nil {
			scores[record] = map[string]float64{}
		}
		scores[record][intervention] = score
	}
	rows.Close()
	out := []classifiedPair{}
	for _, school := range paired {
		then, now := before[school], curr[school]
		if int(now.on.Sub(then.on).Hours()/24) < rules.Dashboard.Outcomes.MinIntervalDays {
			continue
		}
		for _, iv := range rules.Dashboard.Outcomes.Interventions {
			was, ok1 := scores[then.record][iv[0]]
			is, ok2 := scores[now.record][iv[0]]
			if !ok1 || !ok2 {
				continue
			}
			rule := book.rule(iv[0], countries[school])
			classification, delta := changeBetween(was, is, rule)
			out = append(out, classifiedPair{school: school, intervention: iv[0], delta: delta, classification: classification,
				ruleLabel: rule.label, start: then.on, end: now.on})
		}
	}
	return out, nil
}

// schoolVerdicts is change_rules.school_verdicts.
func schoolVerdicts(pairs []classifiedPair, book measurementBook, countries map[string]string) map[string]schoolVerdict {
	grouped, order := map[string][]classifiedPair{}, []string{}
	for _, p := range pairs {
		if _, ok := grouped[p.school]; !ok {
			order = append(order, p.school)
		}
		grouped[p.school] = append(grouped[p.school], p)
	}
	out := map[string]schoolVerdict{}
	for _, school := range order {
		list := grouped[school]
		sum, interventions := 0.0, []string{}
		for _, p := range list {
			sum += p.delta
			interventions = append(interventions, p.intervention)
		}
		mean := math.RoundToEven(sum/float64(len(list))*10000) / 10000
		classification, _ := changeBetween(0, mean, book.schoolRule(interventions, countries[school]))
		out[school] = schoolVerdict{meanDelta: mean, classification: classification}
	}
	return out
}

// changeRow is ia_workflow._change_row.
func changeRow(name string, pairs []classifiedPair, verdicts map[string]schoolVerdict, inScope int, isArea bool) map[string]any {
	byClass := map[string]int{}
	deltas := []float64{}
	n := 0
	if isArea {
		for _, v := range verdicts {
			byClass[v.classification]++
			if v.classification != changeMaintainedStrong {
				deltas = append(deltas, v.meanDelta)
			}
		}
		n = len(verdicts)
	} else {
		for _, p := range pairs {
			byClass[p.classification]++
			if p.classification != changeMaintainedStrong {
				deltas = append(deltas, p.delta)
			}
		}
		n = len(pairs)
	}
	one := 1.0
	var missing *float64
	if inScope > 0 {
		m := 1 - float64(n)/float64(inScope)
		missing = &m
	}
	var median any
	if n >= evidenceMinN {
		median = floatOrNil(medianOf(deltas))
	}
	label := ""
	if len(pairs) > 0 && !isArea {
		label = pairs[0].ruleLabel
	}
	return map[string]any{"name": name, "is_area": isArea, "n": n, "improved": byClass[changeImproved],
		"improved_pct": intOrNil(share(byClass[changeImproved], n)), "declined": byClass[changeDeclined],
		"declined_pct": intOrNil(share(byClass[changeDeclined], n)), "no_change": byClass[changeNoChange],
		"maintained": byClass[changeMaintainedStrong], "median_change": median, "withheld": n > 0 && n < evidenceMinN,
		"grade": evidenceGrade(n, &one, missing), "rule_label": label}
}
