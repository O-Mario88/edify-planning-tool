package plreview

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
)

// periodFigures is one period's figures as refresh_period_targets hands them
// to the database, which rounds them to the column's two places.
type periodFigures struct {
	Actual, Achievement, Status string
}

// figuresFor is refresh_period_targets' arithmetic. A rate's achievement is
// its coverage against the committed rate, the coverage capped at 100 when the
// milestone says so; a rate with no denominator cannot be computed and is an
// honest zero.
func figuresFor(actual, planned pydecimal.Decimal, denominator *pydecimal.Decimal, rate, capped bool) periodFigures {
	hundred := pydecimal.Int(100)
	achievement := pydecimal.Zero()
	switch {
	case rate && denominator != nil && denominator.Sign() != 0:
		coverage := actual.Div(*denominator).Mul(hundred)
		if capped && coverage.Cmp(hundred) > 0 {
			coverage = hundred
		}
		if planned.Sign() != 0 {
			achievement = coverage.Div(planned).Mul(hundred)
		}
	case rate:
	case planned.Sign() != 0:
		achievement = actual.Div(planned).Mul(hundred)
	}
	status := "not_started"
	switch {
	case planned.Sign() != 0 && achievement.Cmp(hundred) >= 0:
		status = "achieved"
	case actual.Sign() != 0:
		status = "in_progress"
	}
	return periodFigures{
		Actual:      actual.String(),
		Achievement: achievement.String(),
		Status:      status,
	}
}

// periodTarget is one MilestonePeriodTarget and what its figures depend on.
type periodTarget struct {
	id, scope, employee, team, project, country, measurement string
	start, end                                               time.Time
	planned                                                  string
	denominator                                              *string
	capped                                                   bool
}

// refreshPeriodTargets is refresh_period_targets for one milestone.
func refreshPeriodTargets(ctx context.Context, tx pgx.Tx, milestone string, now time.Time) error {
	rows, err := tx.Query(ctx, `
SELECT t.id, t.scope, COALESCE(t.employee_id, ''), COALESCE(t.team_id, ''), COALESCE(al.project_id, ''),
       COALESCE(p.country_id, ''), m.measurement_type, t.period_start, t.period_end, t.planned_value::text,
       al.denominator::text, m.cap_at_100
  FROM hr_milestone_period_target t
  JOIN hr_priority_milestone m ON m.id = t.milestone_id
  JOIN hr_strategic_priority p ON p.id = m.priority_id
  LEFT JOIN hr_milestone_allocation al ON al.id = t.allocation_id
 WHERE t.milestone_id = $1`, milestone)
	if err != nil {
		return fmt.Errorf("reading the period targets: %w", err)
	}
	targets, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (periodTarget, error) {
		var t periodTarget
		err := row.Scan(&t.id, &t.scope, &t.employee, &t.team, &t.project, &t.country, &t.measurement,
			&t.start, &t.end, &t.planned, &t.denominator, &t.capped)
		return t, err
	})
	if err != nil {
		return fmt.Errorf("reading a period target: %w", err)
	}
	for _, target := range targets {
		actual, err := periodActual(ctx, tx, milestone, target)
		if err != nil {
			return err
		}
		planned, err := pydecimal.Parse(target.planned)
		if err != nil {
			return fmt.Errorf("reading the planned value of target %s: %w", target.id, err)
		}
		var denominator *pydecimal.Decimal
		if target.denominator != nil {
			parsed, err := pydecimal.Parse(*target.denominator)
			if err != nil {
				return fmt.Errorf("reading the denominator of target %s: %w", target.id, err)
			}
			denominator = &parsed
		}
		figures := figuresFor(actual, planned, denominator, allocations.IsRateMeasurement(target.measurement), target.capped)
		if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.update_period_target($1, $2::numeric, $3::numeric, $4, $5)`,
			target.id, figures.Actual, figures.Achievement, figures.Status, now); err != nil {
			return fmt.Errorf("saving target %s: %w", target.id, err)
		}
	}
	return nil
}

// periodActual is _scoped_credits and _aggregate_credits for one target: the
// verified figure its credits produce, in their counting basis' own unit.
func periodActual(ctx context.Context, tx pgx.Tx, milestone string, t periodTarget) (pydecimal.Decimal, error) {
	scope, scopeArgs, err := creditScope(ctx, tx, t)
	if err != nil {
		return pydecimal.Decimal{}, err
	}
	args := append([]any{milestone, t.start, t.end}, scopeArgs...)
	from := `
  FROM hr_milestone_progress_credit c
  JOIN hr_milestone_activity_rule r ON r.id = c.rule_id
  JOIN activity a ON a.id = c.activity_id
 WHERE r.milestone_id = $1 AND r.active AND c.reversed_at IS NULL AND a.deleted_at IS NULL
   AND a.planned_date >= $2::date AND a.planned_date <= $3::date` + scope
	rows, err := tx.Query(ctx, `SELECT DISTINCT r.counting_basis`+from, args...)
	if err != nil {
		return pydecimal.Decimal{}, fmt.Errorf("reading the counting bases: %w", err)
	}
	bases, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return pydecimal.Decimal{}, fmt.Errorf("reading a counting basis: %w", err)
	}
	var query string
	switch allocations.BasisFamily(bases) {
	case allocations.BasisSchools:
		query = `SELECT COUNT(DISTINCT a.school_id)::text` + from
	case allocations.BasisTeachers:
		query = `SELECT SUM(v)::text FROM (SELECT MAX(a.teachers_attended) AS v` + from + ` GROUP BY c.activity_id) x`
	case allocations.BasisLeaders:
		query = `SELECT SUM(v)::text FROM (SELECT MAX(a.leaders_attended) AS v` + from + ` GROUP BY c.activity_id) x`
	default:
		query = `SELECT SUM(v)::text FROM (SELECT MAX(c.credited_value) AS v` + from + ` GROUP BY c.activity_id) x`
	}
	var total *string
	if err := tx.QueryRow(ctx, query, args...).Scan(&total); err != nil {
		return pydecimal.Decimal{}, fmt.Errorf("adding up the credits: %w", err)
	}
	if total == nil {
		return pydecimal.Zero(), nil
	}
	actual, err := pydecimal.Parse(*total)
	if err != nil {
		return pydecimal.Decimal{}, fmt.Errorf("reading the credits' total: %w", err)
	}
	return actual, nil
}

// creditScope is the branch _scoped_credits takes for this target's scope, as
// a condition on activity `a`. Its arguments follow the query's first three.
func creditScope(ctx context.Context, tx pgx.Tx, t periodTarget) (string, []any, error) {
	const ownedBy = ` AND ((a.responsible_staff_id = ANY($4) AND a.delivery_type IS DISTINCT FROM 'partner')
    OR (a.delivery_type = 'partner' AND a.monitored_by_staff_id = ANY($4)))`
	switch {
	case t.scope == "employee" && t.employee != "":
		owners, err := allocations.OwnerIDs(ctx, tx, t.employee, false)
		if err != nil {
			return "", nil, err
		}
		return ownedBy, []any{owners}, nil
	case t.scope == "team" && t.team != "":
		owners, err := allocations.OwnerIDs(ctx, tx, t.team, true)
		if err != nil {
			return "", nil, err
		}
		return ownedBy, []any{owners}, nil
	case t.scope == "project" && t.project != "":
		return ` AND a.project_id = $4`, []any{t.project}, nil
	case t.country != "":
		return ` AND ` + allocations.CountryActivityClause("$4"), []any{t.country}, nil
	}
	return "", nil, nil
}
