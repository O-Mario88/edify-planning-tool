package clusteroversight

import "math"

const overall = "overall"

// changeRule is one rule of apps.ssa.change_rules: the threshold a move has
// to reach, nil where any movement counts, and the direction expected.
type changeRule struct {
	threshold *float64
	direction string
}

// fallbackRule is the one fallback: with no approved threshold, movement is
// movement.
var fallbackRule = changeRule{direction: "improve"}

// ruleBook is change_rules.RuleBook: every published rule, resolved by
// intervention and country.
type ruleBook map[[2]string]changeRule

// newRuleBook keeps, for each intervention and country, the first rule read:
// the rows arrive newest first.
func newRuleBook(rows []changeRuleRow) ruleBook {
	book := ruleBook{}
	for _, row := range rows {
		if row.Intervention == "" {
			continue
		}
		key := [2]string{row.Intervention, trim(row.Country)}
		if _, seen := book[key]; seen {
			continue
		}
		rule := changeRule{direction: row.Direction}
		if rule.direction == "" {
			rule.direction = "improve"
		}
		if row.Threshold != nil {
			threshold := math.Abs(*row.Threshold)
			rule.threshold = &threshold
		}
		book[key] = rule
	}
	return book
}

// rule is RuleBook.rule: the school's country first, then the
// deployment-wide rule, then the fallback.
func (b ruleBook) rule(intervention, country string) changeRule {
	country = trim(country)
	if country != "" {
		if rule, ok := b[[2]string{intervention, country}]; ok {
			return rule
		}
	}
	if rule, ok := b[[2]string{intervention, ""}]; ok {
		return rule
	}
	return fallbackRule
}

// schoolRule is RuleBook.school_rule: the mean of the thresholds in force
// for the school's compared interventions, one with none counting as 0; the
// fallback where none has one.
func (b ruleBook) schoolRule(interventions []string, country string) changeRule {
	thresholds, any := []float64{}, false
	for _, intervention := range interventions {
		if intervention == "" {
			continue
		}
		rule := b.rule(intervention, country)
		if rule.threshold != nil {
			any = true
			thresholds = append(thresholds, *rule.threshold)
		} else {
			thresholds = append(thresholds, 0)
		}
	}
	if !any {
		return fallbackRule
	}
	threshold := pyRound(mean(thresholds), 2)
	return changeRule{threshold: &threshold, direction: "improve"}
}

// comparable is change_rules.comparable: two readings far enough apart to be
// a before and after. A reading with no date is taken as comparable.
func comparable(start, end string) bool {
	days, ok := daysBetween(start, end)
	return !ok || days >= rules.Change.MinIntervalDays
}

// changeBetween is change_rules.change_between for two readings that are
// both present and comparable: (classification, delta).
func changeBetween(before, after float64, rule changeRule) (string, float64) {
	delta := pyRound(after-before, 2)
	c := rules.Change
	if rule.direction == c.MaintainDirection {
		if after >= c.StrongScore {
			return c.MaintainedStrong, delta
		}
		return c.Declined, delta
	}
	if rule.threshold != nil {
		switch {
		case delta >= *rule.threshold:
			return c.Improved, delta
		case delta <= -*rule.threshold:
			return c.Declined, delta
		}
		return c.NoChange, delta
	}
	switch {
	case delta > 0:
		return c.Improved, delta
	case delta < 0:
		return c.Declined, delta
	}
	return c.NoChange, delta
}

// pair is one school's two readings on one intervention, classified.
type pair struct {
	intervention   string
	before, after  float64
	delta          float64
	classification string
}

// schoolPairs are a school's comparable pairs, in the interventions' order,
// and its verdict across them.
type schoolPairs struct {
	pairs   []pair
	verdict string
}

// classify is the SSA movement's reading of the records
// (profile_insights.ssa_movement_by_cluster): each school with a confirmed
// record in both years is paired on every intervention both records score
// (impact_engine.improvement_rows), each pair judged by its rule
// (change_rules.classify_pairs) unless the two assessments are too close
// together to be a before and after, and the school judged on the mean of
// its pairs' movement (change_rules.school_verdicts).
func classify(r *records, country map[string]string) map[string]schoolPairs {
	book := newRuleBook(r.ChangeRules)
	before := map[string]latestRow{}
	for _, row := range r.LatestBefore {
		before[row.SchoolID] = row
	}
	scores := map[string]map[string]float64{}
	for _, row := range r.PairScores {
		if scores[row.RecordID] == nil {
			scores[row.RecordID] = map[string]float64{}
		}
		scores[row.RecordID][row.Intervention] = row.Score
	}
	out := map[string]schoolPairs{}
	seen := map[string]bool{}
	for _, now := range r.LatestNow {
		then, paired := before[now.SchoolID]
		if !paired || seen[now.SchoolID] {
			continue
		}
		seen[now.SchoolID] = true
		if !comparable(then.TakenOn, now.TakenOn) {
			continue
		}
		school := schoolPairs{}
		deltas, interventions := []float64{}, []string{}
		for _, iv := range rules.SSAInterventions {
			was, hadBefore := scores[then.RecordID][iv[0]]
			is, hasNow := scores[now.RecordID][iv[0]]
			if !hadBefore || !hasNow {
				continue
			}
			classification, delta := changeBetween(was, is, book.rule(iv[0], country[now.SchoolID]))
			school.pairs = append(school.pairs, pair{iv[0], was, is, delta, classification})
			deltas = append(deltas, delta)
			interventions = append(interventions, iv[0])
		}
		if len(school.pairs) == 0 {
			continue
		}
		school.verdict, _ = changeBetween(0, pyRound(mean(deltas), 4), book.schoolRule(interventions, country[now.SchoolID]))
		out[now.SchoolID] = school
	}
	return out
}

// schoolMovementRow is one school's movement on an SSA area or overall.
type schoolMovementRow struct {
	before, after *float64
	change        *float64
	verdict       string
	verdictLabel  string
	tone          string
}

func verdictMeta(v string) (label, tone string) {
	c := rules.Change
	switch v {
	case c.Improved:
		return "Improved", "success"
	case c.MaintainedStrong:
		return "Maintained Strong", "success"
	case c.NoChange:
		return "No Change", "neutral"
	case c.Declined:
		return "Declined", "danger"
	default:
		return "Not Compared", "neutral"
	}
}

// areaMovement is one SSA area's year-on-year movement across a cluster's
// schools (profile_insights.AreaMovement).
type areaMovement struct {
	compared, improved, noChange, maintainedStrong, declined, notCompared int
	// before and after are the means of the compared schools, nil with none.
	before, after *float64
	// verdicts is each compared member's classification.
	verdicts map[string]string
	// schools is each member school's movement row, keyed by school id.
	schools map[string]schoolMovementRow
}

// held is AreaMovement.held (no_change + maintained_strong).
func (a areaMovement) held() int { return a.noChange + a.maintainedStrong }

// change is AreaMovement.change.
func (a areaMovement) change() *float64 {
	if a.before == nil || a.after == nil {
		return nil
	}
	change := pyRound(*a.after-*a.before, 1)
	return &change
}

func (a *areaMovement) count(school, classification string) {
	a.compared++
	switch classification {
	case rules.Change.Improved:
		a.improved++
	case rules.Change.NoChange:
		a.noChange++
	case rules.Change.MaintainedStrong:
		a.maintainedStrong++
	case rules.Change.Declined:
		a.declined++
	}
	a.verdicts[school] = classification
}

// meanOrNil is profile_insights._mean: the mean to one place, nil of none.
func meanOrNil(values []float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	m := pyRound(mean(values), 1)
	return &m
}

// movementOf is profile_insights._movement_of for one cluster: the overall
// row (each school's verdict across its areas, not an average of the area
// rows) and one row for each intervention.
func movementOf(members []string, classified map[string]schoolPairs) map[string]*areaMovement {
	out := map[string]*areaMovement{
		overall: {verdicts: map[string]string{}, schools: map[string]schoolMovementRow{}},
	}
	areaBefores := map[string][]float64{}
	areaAfters := map[string][]float64{}
	for _, iv := range rules.SSAInterventions {
		out[iv[0]] = &areaMovement{verdicts: map[string]string{}, schools: map[string]schoolMovementRow{}}
	}
	notComparedRow := schoolMovementRow{verdict: "not_compared", verdictLabel: "Not Compared", tone: "neutral"}
	befores, afters := []float64{}, []float64{}
	for _, school := range members {
		found, ok := classified[school]
		if !ok {
			out[overall].notCompared++
			out[overall].schools[school] = notComparedRow
			for _, iv := range rules.SSAInterventions {
				out[iv[0]].notCompared++
				out[iv[0]].schools[school] = notComparedRow
			}
			continue
		}
		was, is := []float64{}, []float64{}
		scored := map[string]bool{}
		for _, p := range found.pairs {
			was, is = append(was, p.before), append(is, p.after)
			out[p.intervention].count(school, p.classification)
			areaBefores[p.intervention] = append(areaBefores[p.intervention], p.before)
			areaAfters[p.intervention] = append(areaAfters[p.intervention], p.after)
			pb, pa := pyRound(p.before, 1), pyRound(p.after, 1)
			pc := pyRound(pa-pb, 1)
			lbl, tn := verdictMeta(p.classification)
			out[p.intervention].schools[school] = schoolMovementRow{
				before: &pb, after: &pa, change: &pc,
				verdict: p.classification, verdictLabel: lbl, tone: tn,
			}
			scored[p.intervention] = true
		}
		for _, iv := range rules.SSAInterventions {
			if !scored[iv[0]] {
				out[iv[0]].notCompared++
				out[iv[0]].schools[school] = notComparedRow
			}
		}
		out[overall].count(school, found.verdict)
		ob, oa := pyRound(mean(was), 1), pyRound(mean(is), 1)
		oc := pyRound(oa-ob, 1)
		olbl, otn := verdictMeta(found.verdict)
		out[overall].schools[school] = schoolMovementRow{
			before: &ob, after: &oa, change: &oc,
			verdict: found.verdict, verdictLabel: olbl, tone: otn,
		}
		befores, afters = append(befores, ob), append(afters, oa)
	}
	out[overall].before, out[overall].after = meanOrNil(befores), meanOrNil(afters)
	for _, iv := range rules.SSAInterventions {
		out[iv[0]].before = meanOrNil(areaBefores[iv[0]])
		out[iv[0]].after = meanOrNil(areaAfters[iv[0]])
	}
	return out
}
