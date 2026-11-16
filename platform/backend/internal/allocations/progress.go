package allocations

import (
	"context"
	"fmt"
	"math"
	"math/big"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

func anyIn(bases map[string]bool, set []string) bool {
	for b := range bases {
		if slices.Contains(set, b) {
			return true
		}
	}
	return false
}

// matchOf is the OR of a milestone's rules (and its year) on activity `a`.
func matchOf(rs []rule, fy string, args *[]any) string {
	parts := []string{}
	for _, r := range rs {
		parts = append(parts, ruleMatch(r, args))
	}
	*args = append(*args, fy)
	return "(" + strings.Join(parts, " OR ") + ") AND a.fy = " + fmt.Sprintf("$%d", len(*args))
}

// planProgress is milestone_plan_progress over the scoped activities: for
// each milestone with an active rule, its planned, completed and verified
// figures in the unit its rules count, against its target.
func planProgress(ctx context.Context, db schooldirectory.Querier, milestones []string, groups map[string][]allocation, rulesOf map[string][]rule,
	fy, scope string, scopeArgs []any, targets map[string]*big.Rat, today time.Time) (map[string]*Progress, error) {
	out := map[string]*Progress{}
	for _, mid := range milestones {
		rs := rulesOf[mid]
		if len(rs) == 0 {
			continue
		}
		args := append([]any{}, scopeArgs...)
		match := matchOf(rs, fy, &args)
		bases := map[string]bool{}
		for _, r := range rs {
			bases[r.basis] = true
		}
		args = append(args, rules.PlannedStatuses, rules.CompletedStatuses)
		planned, completed := fmt.Sprintf("a.status = ANY($%d)", len(args)-1), fmt.Sprintf("a.status = ANY($%d)", len(args))
		var sel string
		unit := "activities"
		switch {
		case anyIn(bases, rules.SchoolBases):
			unit = "schools"
			sel = fmt.Sprintf("COUNT(DISTINCT a.school_id) FILTER (WHERE %s), COUNT(DISTINCT a.school_id) FILTER (WHERE %s)", planned, completed)
		case anyIn(bases, rules.TeacherBases) || anyIn(bases, rules.LeaderBases):
			field := "leaders_attended"
			unit = "leaders"
			if anyIn(bases, rules.TeacherBases) {
				unit, field = "teachers", "teachers_attended"
			}
			sel = fmt.Sprintf("COALESCE(SUM(a.expected_participants) FILTER (WHERE %s), 0), COALESCE(SUM(a.%s) FILTER (WHERE %s), 0)", planned, field, completed)
		default:
			sel = fmt.Sprintf("COUNT(*) FILTER (WHERE %s), COUNT(*) FILTER (WHERE %s)", planned, completed)
		}
		pr := &Progress{Unit: unit, Year: fy, Target: targets[mid]}
		if err := db.QueryRow(ctx, "SELECT "+sel+" FROM activity a WHERE "+scope+" AND "+match, args...).Scan(&pr.Planned, &pr.Completed); err != nil {
			return nil, fmt.Errorf("allocations: reading the plan of a milestone: %w", err)
		}
		// Verified: distinct credited schools for a school basis, else the
		// largest attendance or credited value per activity, summed.
		vargs := append([]any{}, scopeArgs...)
		vmatch := matchOf(rs, fy, &vargs)
		owned := "SELECT a.id FROM activity a WHERE " + scope + " AND " + vmatch
		vargs = append(vargs, mid)
		m := fmt.Sprintf("$%d", len(vargs))
		var verified *string
		if anyIn(bases, rules.SchoolBases) {
			err := db.QueryRow(ctx, `
SELECT COUNT(DISTINCT act.school_id)::text FROM hr_milestone_progress_credit c JOIN hr_milestone_activity_rule r ON r.id = c.rule_id
JOIN activity act ON act.id = c.activity_id
WHERE r.active AND c.reversed_at IS NULL AND r.milestone_id = `+m+` AND c.activity_id IN (`+owned+`)`, vargs...).Scan(&verified)
			if err != nil {
				return nil, fmt.Errorf("allocations: reading a milestone's verified schools: %w", err)
			}
		} else {
			field := creditField(bases)
			err := db.QueryRow(ctx, `
SELECT SUM(v)::text FROM (
  SELECT MAX(`+field+`) AS v FROM hr_milestone_progress_credit c JOIN hr_milestone_activity_rule r ON r.id = c.rule_id
  JOIN activity act ON act.id = c.activity_id
  WHERE r.active AND c.reversed_at IS NULL AND r.milestone_id = `+m+` AND c.activity_id IN (`+owned+`)
  GROUP BY c.activity_id) per`, vargs...).Scan(&verified)
			if err != nil {
				return nil, fmt.Errorf("allocations: reading a milestone's verified figure: %w", err)
			}
		}
		pr.Verified = orZero(rat(verified))
		pr.HasWork = pr.Planned != 0 || pr.Completed != 0
		n, _ := strconv.Atoi(fy)
		pr.Started = !time.Date(n-1, time.October, 1, 0, 0, 0, 0, time.UTC).After(today)
		if pr.Target != nil {
			tf, _ := pr.Target.Float64()
			share := func(v int64) *float64 {
				if tf == 0 {
					return nil
				}
				x := round(math.Min(float64(v)/tf*100.0, 100.0), 1)
				return &x
			}
			pr.Pct, pr.PlannedPct = share(pr.Completed), share(pr.Planned)
		}
		out[mid] = pr
	}
	return out, nil
}

// creditField is the activity column (or the credit's own value) a
// non-school basis sums.
func creditField(bases map[string]bool) string {
	switch {
	case anyIn(bases, rules.TeacherBases):
		return "act.teachers_attended"
	case anyIn(bases, rules.LeaderBases):
		return "act.leaders_attended"
	}
	return "c.credited_value"
}

// aggregateCredits is aggregate_credits_by_milestone over the live credits
// of the milestones' active rules whose activity is in the scope.
func aggregateCredits(ctx context.Context, db schooldirectory.Querier, basesOf map[string]map[string]bool, _ string, scope string, scopeArgs []any) (map[string]*string, error) {
	out := map[string]*string{}
	for mid, bases := range basesOf {
		args := append([]any{}, scopeArgs...)
		args = append(args, mid)
		m := fmt.Sprintf("$%d", len(args))
		inScope := "SELECT a.id FROM activity a WHERE " + scope
		var value *string
		var err error
		if anyIn(bases, rules.SchoolBases) {
			err = db.QueryRow(ctx, `
SELECT COUNT(DISTINCT act.school_id)::text FROM hr_milestone_progress_credit c JOIN hr_milestone_activity_rule r ON r.id = c.rule_id
JOIN activity act ON act.id = c.activity_id
WHERE r.active AND c.reversed_at IS NULL AND r.milestone_id = `+m+` AND c.activity_id IN (`+inScope+`)`, args...).Scan(&value)
		} else {
			err = db.QueryRow(ctx, `
SELECT SUM(v)::text FROM (
  SELECT MAX(`+creditField(bases)+`) AS v FROM hr_milestone_progress_credit c JOIN hr_milestone_activity_rule r ON r.id = c.rule_id
  JOIN activity act ON act.id = c.activity_id
  WHERE r.active AND c.reversed_at IS NULL AND r.milestone_id = `+m+` AND c.activity_id IN (`+inScope+`)
  GROUP BY c.activity_id) per`, args...).Scan(&value)
		}
		if err != nil {
			return nil, fmt.Errorf("allocations: reading a milestone's credits: %w", err)
		}
		out[mid] = value
	}
	return out, nil
}
