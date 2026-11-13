package planningpage

import (
	"context"
	"fmt"
	"math"
	"strconv"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func count(ctx context.Context, q schooldirectory.Querier, what, sql string, args ...any) (int, error) {
	var n int
	if err := q.QueryRow(ctx, sql, args...).Scan(&n); err != nil {
		return 0, fmt.Errorf("planningpage: counting %s: %w", what, err)
	}
	return n, nil
}

// stripBlock is get_dashboard_data's ten figures over the whole direct
// portfolio (base, a condition over the schools aliased s), for the year fy.
func stripBlock(ctx context.Context, q schooldirectory.Querier, base string, baseArgs []any, fy string) (*screensv1.PageBlock, error) {
	// Each statement numbers its own parameters after the portfolio's.
	with := func(more ...any) []any { return append(append([]any{}, baseArgs...), more...) }
	n := len(baseArgs)
	p := func(i int) string { return "$" + strconv.Itoa(n+i) }
	portfolio := "SELECT s.id FROM school s WHERE " + base
	clustered := "s.cluster_id IS NOT NULL AND s.cluster_id <> ''"

	var hasCatalogue bool
	if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cost_catalogue WHERE country = $1 AND kind = $2 AND status = $3 AND is_active)`,
		rules.Catalogue.Country, rules.Catalogue.Kind, rules.Catalogue.Status).Scan(&hasCatalogue); err != nil {
		return nil, fmt.Errorf("planningpage: reading the cost catalogue: %w", err)
	}
	costBlocked := 0
	if !hasCatalogue {
		var err error
		if costBlocked, err = count(ctx, q, "cost blocked", "SELECT count(*) FROM school s WHERE "+base+" AND "+clustered, baseArgs...); err != nil {
			return nil, err
		}
	}
	blockers := schooldirectory.PlanningBlockers()
	cleanup, err := count(ctx, q, "data cleanup", "SELECT count(*) FROM school s WHERE "+base+" AND "+clustered+" AND "+blockers, baseArgs...)
	if err != nil {
		return nil, err
	}

	// Ready for Support and SSA Required: the clustered schools with every
	// detail, no work in the plan this year and no hand-over waiting for a
	// date, split by whether any confirmed assessment is on record.
	var ready, baseline int
	err = q.QueryRow(ctx, fmt.Sprintf(`
WITH clean AS (SELECT s.id FROM school s WHERE %[1]s AND %[2]s AND NOT %[3]s),
busy AS (
  SELECT a.school_id AS id FROM activity a WHERE a.deleted_at IS NULL AND a.fy = %[4]s
    AND a.school_id IN (%[5]s) AND NOT (a.status = ANY(%[6]s))
  UNION SELECT pa.school_id FROM partner_assignment pa WHERE pa.school_id IN (%[5]s) AND pa.status = ANY(%[7]s)),
assessed AS (SELECT r.school_id AS id FROM ssa_record r WHERE r.school_id IN (%[5]s)
  AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL)
SELECT COUNT(*) FILTER (WHERE c.id IN (SELECT id FROM assessed)), COUNT(*) FILTER (WHERE c.id NOT IN (SELECT id FROM assessed WHERE id IS NOT NULL))
FROM clean c WHERE c.id NOT IN (SELECT id FROM busy WHERE id IS NOT NULL)`,
		base, clustered, blockers, p(1), portfolio, p(2), p(3)),
		with(fy, rules.NotInPlanActivityStatuses, rules.PartnerPendingStatuses)...).Scan(&ready, &baseline)
	if err != nil {
		return nil, fmt.Errorf("planningpage: counting readiness: %w", err)
	}

	partnerPending, err := count(ctx, q, "partner pending", fmt.Sprintf(
		"SELECT count(*) FROM partner_assignment pa WHERE pa.school_id IN (%s) AND pa.status = ANY(%s)", portfolio, p(1)),
		with(rules.PartnerPendingStatuses)...)
	if err != nil {
		return nil, err
	}
	scopedClusters := fmt.Sprintf("SELECT DISTINCT s.cluster_id FROM school s WHERE %s AND %s", base, clustered)
	inScope := fmt.Sprintf("(a.school_id IN (%s) OR (a.school_id IS NULL AND a.cluster_id IN (%s)))", portfolio, scopedClusters)
	inPlan, err := count(ctx, q, "in my plan", fmt.Sprintf(
		"SELECT count(*) FROM activity a WHERE a.deleted_at IS NULL AND a.fy = %s AND NOT (a.status = ANY(%s)) AND %s",
		p(1), p(2), inScope), with(fy, rules.NotInThePlan)...)
	if err != nil {
		return nil, err
	}
	judged, informed := 0, 0
	if err := each(ctx, q, "plan verdicts", fmt.Sprintf(`
SELECT a.ssa_alignment, count(*) FROM activity a WHERE a.deleted_at IS NULL AND a.fy = %s AND a.status = ANY(%s)
  AND %s AND NOT (a.ssa_alignment = '' AND a.ssa_alignment IS NOT NULL) GROUP BY a.ssa_alignment`, p(1), p(2), inScope),
		func(rows pgx.Rows) error {
			var verdict *string
			var n int
			if err := rows.Scan(&verdict, &n); err != nil {
				return err
			}
			judged += n
			if verdict != nil && in(rules.InformedAlignments, *verdict) {
				informed += n
			}
			return nil
		}, with(fy, rules.LivePlanStatuses)...); err != nil {
		return nil, err
	}
	coreGaps, err := count(ctx, q, "core package gaps", fmt.Sprintf(`
SELECT count(*) FROM school s WHERE %s AND s.school_type = 'core' AND NOT EXISTS (
  SELECT 1 FROM activity a WHERE a.school_id = s.id AND a.deleted_at IS NULL AND a.fy = %s AND a.status = ANY(%s))`,
		base, p(1), p(2)), with(fy, rules.CompletedWorkStatuses)...)
	if err != nil {
		return nil, err
	}
	clustersNeeding, err := count(ctx, q, "clusters needing action", fmt.Sprintf(`
SELECT count(*) FROM (%s) c WHERE c.cluster_id NOT IN (
  SELECT a.cluster_id FROM activity a WHERE a.cluster_id IN (%s) AND a.deleted_at IS NULL AND a.fy = %s
    AND NOT (a.status = ANY(%s)) AND a.cluster_id IS NOT NULL)`, scopedClusters, scopedClusters, p(1), p(2)),
		with(fy, rules.NotInPlanActivityStatuses)...)
	if err != nil {
		return nil, err
	}
	unclustered, err := count(ctx, q, "unclustered", "SELECT count(*) FROM school s WHERE "+base+" AND (s.cluster_id IS NULL OR s.cluster_id = '')", baseArgs...)
	if err != nil {
		return nil, err
	}

	informedValue, informedHelper := "—", "no live plans yet"
	if judged > 0 {
		informedValue = strconv.Itoa(int(math.RoundToEven(float64(informed)/float64(judged)*100))) + "%"
		informedHelper = fmt.Sprintf("%d of %d need attention", judged-informed, judged)
	}
	l := rules.StripLabels
	figure := func(label string, n int, helper string) schoolprofile.StripFigure {
		return schoolprofile.StripFigure{Label: label, Value: strconv.Itoa(n), Helper: helper}
	}
	return schoolprofile.Strip("Planning context", []schoolprofile.StripFigure{
		figure(l[0], ready, "Clustered & SSA active"),
		figure(l[1], baseline, "No confirmed SSA on record"),
		figure("Not grouped in cluster", unclustered, "Schools awaiting grouping"),
		figure(l[2], clustersNeeding, "No activity planned this year"),
		figure(l[3], coreGaps, "Core schools with nothing completed this year"),
		figure(l[4], partnerPending, "Partner awaiting schedule"),
		figure(l[5], inPlan, "Activities in this year's plan"),
		{Label: l[6], Value: informedValue, Helper: informedHelper},
		figure(l[7], costBlocked, "Missing Cost Catalogue"),
		figure(l[8], cleanup, "Missing operational fields"),
	}), nil
}
