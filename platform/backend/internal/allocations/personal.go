package allocations

import (
	"context"
	"errors"
	"fmt"
	"math"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNotDrawn is a person's milestone whose projection Go does not draw: an
// allocation that is not the person's own (a team's, a Project's), or a
// milestone without its metric definition (which the existing page cannot
// name either).
var ErrNotDrawn = errors.New("allocations: a milestone projection Go does not draw")

// Classification is classify_achievement's answer.
type Classification struct {
	Key, Label, Tone string
	Pct              *float64
	Scoring          bool
}

// Cell is one period of a milestone's projection (period_cell): its target,
// what was achieved, and the share.
type Cell struct {
	Target, Actual pydecimal.Decimal
	Pct            *int
}

// Milestone is _allocation_projection: one of a person's approved
// allocations, projected over a month of the year.
type Milestone struct {
	AllocationID, Priority, Title, DataSource string
	MonthPlan, MonthActual                    pydecimal.Decimal
	QuarterPlan, QuarterActual                pydecimal.Decimal
	FYPlan, FYActual, Remaining               pydecimal.Decimal
	// Progress is round(fy_actual / fy_plan × 100, 1); nil when the plan
	// is zero (the existing page's integer 0).
	Progress *float64
	Cells    []Cell // the month, Q1 to Q4, the year
	Class    Classification
	Linked   int
}

type periodRow struct {
	kind                         string
	start, end                   time.Time
	planned, actual, achievement pydecimal.Decimal
}

type personal struct {
	id, milestoneID, kind, title, measurement, priority string
	definition                                          *string
	capAt100                                            bool
	allocated                                           pydecimal.Decimal
	months, quarters                                    []periodRow
}

// Personal is personal_milestone_targets: the person's approved
// allocations of the year on any milestone, in the plan's order, each
// projected over month (1–12) of the year.
func Personal(ctx context.Context, db schooldirectory.Querier, staffID, fy string, month int) ([]Milestone, error) {
	rows, err := db.Query(ctx, `
SELECT a.id, a.milestone_id, COALESCE(a.allocated_to_type, ''), COALESCE(m.title, ''), COALESCE(m.measurement_type, ''), m.cap_at_100,
       COALESCE(sp.title, ''), d.canonical_label, a.allocated_target::text
FROM hr_milestone_allocation a JOIN hr_priority_milestone m ON m.id = a.milestone_id
JOIN hr_strategic_priority sp ON sp.id = m.priority_id
LEFT JOIN hr_milestone_metric_definition d ON d.id = m.metric_definition_id
WHERE a.employee_id = $1 AND a.status = 'approved' AND sp.fy = $2
ORDER BY sp.sequence, m.source_order, m.code, m.id, a.id`, staffID, fy)
	if err != nil {
		return nil, fmt.Errorf("allocations: reading the person's allocations: %w", err)
	}
	var list []*personal
	for rows.Next() {
		var a personal
		var allocated *string
		if err := rows.Scan(&a.id, &a.milestoneID, &a.kind, &a.title, &a.measurement, &a.capAt100, &a.priority, &a.definition, &allocated); err != nil {
			rows.Close()
			return nil, fmt.Errorf("allocations: reading an allocation: %w", err)
		}
		if a.kind != "employee" || a.definition == nil {
			rows.Close()
			return nil, ErrNotDrawn
		}
		a.allocated = decOf(allocated)
		list = append(list, &a)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(list) == 0 {
		return nil, nil
	}
	if err := readPeriods(ctx, db, list); err != nil {
		return nil, err
	}
	milestones := []string{}
	for _, a := range list {
		if !slices.Contains(milestones, a.milestoneID) {
			milestones = append(milestones, a.milestoneID)
		}
	}
	rulesOf, err := readRules(ctx, db, milestones)
	if err != nil {
		return nil, err
	}
	owners, err := ownerIDs(ctx, db, staffID, false)
	if err != nil {
		return nil, err
	}
	linked, err := linkedActivities(ctx, db, list, owners)
	if err != nil {
		return nil, err
	}
	out := []Milestone{}
	for _, a := range list {
		bases := map[string]bool{}
		for _, r := range rulesOf[a.milestoneID] {
			bases[r.basis] = true
		}
		spanActual := func(span []periodRow) (pydecimal.Decimal, error) {
			return rangeActual(ctx, db, a.milestoneID, bases, owners, span)
		}
		m, err := project(a, month, spanActual)
		if err != nil {
			return nil, err
		}
		m.Linked = linked[a.milestoneID]
		out = append(out, m)
	}
	return out, nil
}

func readPeriods(ctx context.Context, db schooldirectory.Querier, list []*personal) error {
	ids := []string{}
	byID := map[string]*personal{}
	for _, a := range list {
		ids = append(ids, a.id)
		byID[a.id] = a
	}
	rows, err := db.Query(ctx, `SELECT allocation_id, period_type, period_start, period_end, planned_value::text, actual_value::text,
       achievement_percentage::text
FROM hr_milestone_period_target WHERE allocation_id = ANY($1) AND period_type IN ('month', 'quarter')
ORDER BY period_start`, ids)
	if err != nil {
		return fmt.Errorf("allocations: reading the period targets: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var r periodRow
		var planned, actual, achievement *string
		if err := rows.Scan(&id, &r.kind, &r.start, &r.end, &planned, &actual, &achievement); err != nil {
			return fmt.Errorf("allocations: reading a period target: %w", err)
		}
		r.planned, r.actual, r.achievement = decOf(planned), decOf(actual), decOf(achievement)
		if r.kind == "month" {
			byID[id].months = append(byID[id].months, r)
		} else {
			byID[id].quarters = append(byID[id].quarters, r)
		}
	}
	return rows.Err()
}

// rangeActual is range_actual for an employee's allocation: the verified
// figure of the milestone's live credits on the person's work planned
// across the span the rows cover.
func rangeActual(ctx context.Context, db schooldirectory.Querier, milestone string, bases map[string]bool, owners []string,
	span []periodRow) (pydecimal.Decimal, error) {
	if len(span) == 0 {
		return pydecimal.Zero(), nil
	}
	start, end := span[0].start, span[0].end
	for _, r := range span {
		if r.start.Before(start) {
			start = r.start
		}
		if r.end.After(end) {
			end = r.end
		}
	}
	scope := `a.deleted_at IS NULL AND ((a.responsible_staff_id = ANY($1) AND a.delivery_type IS DISTINCT FROM 'partner')
 OR (a.delivery_type = 'partner' AND a.monitored_by_staff_id = ANY($1))) AND a.planned_date >= $2::date AND a.planned_date <= $3::date`
	values, err := aggregateCredits(ctx, db, map[string]map[string]bool{milestone: bases}, "", scope, []any{owners, start, end})
	if err != nil {
		return pydecimal.Zero(), err
	}
	got := decOf(values[milestone])
	if got.Sign() == 0 {
		return pydecimal.Zero(), nil
	}
	return got, nil
}

// linkedActivities is _linked_activity_counts for one person: the explicit
// planning links of each milestone's allocation and the work its live
// credits came from, in the person's hands, counted once each.
func linkedActivities(ctx context.Context, db schooldirectory.Querier, list []*personal, owners []string) (map[string]int, error) {
	ids, milestones := []string{}, []string{}
	milestoneOf := map[string]string{}
	for _, a := range list {
		ids = append(ids, a.id)
		milestones = append(milestones, a.milestoneID)
		milestoneOf[a.id] = a.milestoneID
	}
	seen := map[string]map[string]bool{}
	add := func(m, activity string) {
		if seen[m] == nil {
			seen[m] = map[string]bool{}
		}
		seen[m][activity] = true
	}
	rows, err := db.Query(ctx, `SELECT allocation_id, activity_id FROM hr_activity_priority_link WHERE allocation_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("allocations: reading the planning links: %w", err)
	}
	for rows.Next() {
		var allocation, activity string
		if err := rows.Scan(&allocation, &activity); err != nil {
			rows.Close()
			return nil, fmt.Errorf("allocations: reading a planning link: %w", err)
		}
		add(milestoneOf[allocation], activity)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(ctx, `SELECT r.milestone_id, c.activity_id FROM hr_milestone_progress_credit c
JOIN hr_milestone_activity_rule r ON r.id = c.rule_id JOIN activity act ON act.id = c.activity_id
WHERE r.milestone_id = ANY($1) AND c.reversed_at IS NULL
  AND (act.responsible_staff_id = ANY($2) OR act.monitored_by_staff_id = ANY($2))`, milestones, owners)
	if err != nil {
		return nil, fmt.Errorf("allocations: reading the credited work: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var m, activity string
		if err := rows.Scan(&m, &activity); err != nil {
			return nil, fmt.Errorf("allocations: reading the credited work: %w", err)
		}
		add(m, activity)
	}
	out := map[string]int{}
	for m, set := range seen {
		out[m] = len(set)
	}
	return out, rows.Err()
}

var (
	hundred = pydecimal.Int(100)
	cent    = -2
)

func sumPlanned(rows []periodRow) pydecimal.Decimal {
	s := pydecimal.Zero()
	for _, r := range rows {
		s = s.Add(r.planned)
	}
	return s
}

func bestAchievement(rows []periodRow) pydecimal.Decimal {
	best := pydecimal.Zero()
	for i, r := range rows {
		if i == 0 || r.achievement.Cmp(best) > 0 {
			best = r.achievement
		}
	}
	return best
}

// share is round(float(actual / target × 100)), nil for a zero target.
func share(actual, target pydecimal.Decimal) *int {
	if target.Sign() == 0 {
		return nil
	}
	v := int(math.RoundToEven(actual.Div(target).Mul(hundred).Float64()))
	return &v
}

// project is _allocation_projection.
func project(a *personal, month int, spanActual func([]periodRow) (pydecimal.Decimal, error)) (Milestone, error) {
	summable := a.measurement == "count" || a.measurement == "currency"
	m := Milestone{AllocationID: a.id, Priority: a.priority, Title: a.title, DataSource: *a.definition}
	periods := a.months
	var current *periodRow
	if len(periods) >= month {
		current = &periods[month-1]
	}
	qs := ((month - 1) / 3) * 3
	quarter := periods[min(qs, len(periods)):min(qs+3, len(periods))]
	achievedRate := func(rows []periodRow, plan pydecimal.Decimal) pydecimal.Decimal {
		return bestAchievement(rows).Mul(plan).Div(hundred).Quantize(cent)
	}
	var err error
	if summable {
		if len(periods) > 0 {
			m.FYPlan = sumPlanned(periods)
		} else {
			m.FYPlan = a.allocated
		}
		if m.FYActual, err = spanActual(periods); err != nil {
			return m, err
		}
		m.QuarterPlan = sumPlanned(quarter)
		if m.QuarterActual, err = spanActual(quarter); err != nil {
			return m, err
		}
	} else {
		m.FYPlan = a.allocated
		m.FYActual = achievedRate(periods, m.FYPlan)
		m.QuarterPlan = m.FYPlan
		m.QuarterActual = achievedRate(quarter, m.FYPlan)
	}
	m.Remaining = pydecimal.Max(pydecimal.Zero(), m.FYPlan.Sub(m.FYActual))
	m.MonthPlan, m.MonthActual = pydecimal.Zero(), pydecimal.Zero()
	if current != nil {
		m.MonthPlan = current.planned
		if summable {
			m.MonthActual = current.actual
		} else {
			m.MonthActual = current.achievement.Mul(m.FYPlan).Div(hundred).Quantize(cent)
		}
	}
	if m.FYPlan.Sign() != 0 {
		p := round(m.FYActual.Div(m.FYPlan).Mul(hundred).Float64(), 1)
		m.Progress = &p
	}
	cell := func(rows []periodRow, override *pydecimal.Decimal) (Cell, error) {
		var c Cell
		if summable {
			c.Target = sumPlanned(rows)
			if override != nil {
				c.Actual = *override
			} else if c.Actual, err = spanActual(rows); err != nil {
				return c, err
			}
		} else {
			c.Target = a.allocated
			if override != nil {
				c.Actual = *override
			} else {
				c.Actual = bestAchievement(rows).Mul(c.Target).Div(hundred).Quantize(cent)
			}
		}
		c.Pct = share(c.Actual, c.Target)
		return c, nil
	}
	var monthRows []periodRow
	if current != nil {
		monthRows = []periodRow{*current}
	}
	first, err := cell(monthRows, &m.MonthActual)
	if err != nil {
		return m, err
	}
	m.Cells = append(m.Cells, first)
	for q := 0; q < 4; q++ {
		var override *pydecimal.Decimal
		if q < len(a.quarters) {
			v := a.quarters[q].actual
			if !summable {
				v = a.quarters[q].achievement.Mul(m.FYPlan).Div(hundred).Quantize(cent)
			}
			override = &v
		}
		c, err := cell(periods[min(q*3, len(periods)):min(q*3+3, len(periods))], override)
		if err != nil {
			return m, err
		}
		m.Cells = append(m.Cells, c)
	}
	year, err := cell(periods, &m.FYActual)
	if err != nil {
		return m, err
	}
	m.Cells = append(m.Cells, year)
	var pct *float64
	if m.FYPlan.Sign() != 0 {
		pct = m.Progress
	}
	var ceiling *pydecimal.Decimal
	if !summable {
		ceiling = RateCeiling(m.FYPlan)
	}
	m.Class = Classify(pct, a.capAt100, ceiling, &m.FYPlan)
	return m, nil
}

// RateCeiling is rate_achievement_ceiling: the achievement full coverage
// earns against a rate target; nil for a rate of zero or less.
func RateCeiling(rate pydecimal.Decimal) *pydecimal.Decimal {
	if rate.Sign() <= 0 {
		return nil
	}
	v := hundred.Div(rate).Mul(hundred).Quantize(cent)
	return &v
}

// Classify is classify_achievement (scoreable): the five approved bands,
// or the honest state of a target of zero or a share not yet started.
func Classify(pct *float64, capAt100 bool, ceiling, target *pydecimal.Decimal) Classification {
	state := func(key string) Classification {
		s := rules.NonScoringStates[key]
		return Classification{Key: key, Label: s[0], Tone: s[1]}
	}
	if target != nil && target.Sign() == 0 {
		return state("not_applicable")
	}
	if pct == nil {
		return state("not_started")
	}
	value, err := pydecimal.Parse(Repr(*pct))
	if err != nil {
		return state("configuration_required")
	}
	value = value.Quantize(cent)
	if capAt100 {
		bound := hundred
		if ceiling != nil {
			bound = *ceiling
		}
		if value.Cmp(bound) > 0 {
			value = bound.Quantize(cent)
		}
	}
	key, label, tone := rules.FarExceeded[0], rules.FarExceeded[1], rules.FarExceeded[2]
	for _, b := range rules.AchievementBands {
		bound := pydecimal.MustParse(b.Bound)
		if c := value.Cmp(bound); c < 0 || (b.Inclusive && c == 0) {
			key, label, tone = b.Key, b.Label, b.Tone
			break
		}
	}
	f := value.Float64()
	return Classification{Key: key, Label: label, Tone: tone, Pct: &f, Scoring: true}
}
