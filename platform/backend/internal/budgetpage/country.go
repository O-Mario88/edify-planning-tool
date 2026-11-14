package budgetpage

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
)

// countryRules are the country Budget's rules (rules.json "country").
type countryRules struct {
	HomeCountryID         string            `json:"home_country_id"`
	LockedStatuses        []string          `json:"locked_statuses"`
	ApprovedLimitStatuses []string          `json:"approved_limit_statuses"`
	ApprovalStatusLabels  map[string]string `json:"approval_status_labels"`
	ReadRoles             []string          `json:"read_roles"`
	CDRoles               []string          `json:"cd_roles"`
	RVPRoles              []string          `json:"rvp_roles"`
	Months                []string          `json:"months"`
	MoneyMovedStatuses    []string          `json:"money_moved_statuses"`
	Finance               struct {
		Pending   []string `json:"pending"`
		Confirmed []string `json:"confirmed"`
		Disbursed []string `json:"disbursed"`
		Accounted []string `json:"accounted"`
	} `json:"finance"`
}

// workflow is what the page shows of get_country_monthly_budget: the month's
// budget as the existing page leaves it after its read. The existing page
// creates the month's budget when there is none and, while the month is not
// locked, writes its live totals back; Go writes neither (owner,
// 2026-11-14: "Go reads it anyway"). It shows the values that read would
// store: a month with no budget is a draft, and a live month's request is
// its planned activities' cost.
type workflow struct {
	exists                        bool
	id, status                    string
	month                         int
	total, operationalRequirement int64
	priorPending                  string
	rec                           reconciliation
}

type reconciliation struct {
	committed, disbursed, accounted, returned, reimbursed int64
}

// financeHealth is CDAnalyticsService.budget_finance_health for the year,
// unfiltered: the advances of the year's live activities.
type financeHealth struct {
	requested, pending, confirmed, disbursed, accounted, returned int64
	quarters                                                      [4]int64
}

type district struct{ id, name string }

func monthKey(fy, month int) string {
	year := fy
	if month >= 10 {
		year = fy - 1
	}
	return fmt.Sprintf("%d-%02d", year, month)
}

func (w workflow) locked() bool { return in(rules.Country.LockedStatuses, w.status) }

func (w workflow) approvalStatus() string {
	if l, ok := rules.Country.ApprovalStatusLabels[w.status]; ok {
		return l
	}
	return "Draft"
}

// multiCountry is reconciliation_service._is_multi_country: the advances are
// then split by their owner's country, which Go does not read.
func (s *Service) multiCountry(ctx context.Context) (bool, error) {
	var n int
	err := s.db.QueryRow(ctx, `
		SELECT count(DISTINCT country) FROM staff_profile
		WHERE deleted_at IS NULL AND country IS NOT NULL AND country <> ''`).Scan(&n)
	if err != nil {
		return false, fmt.Errorf("budgetpage: counting the countries: %w", err)
	}
	return n > 1, nil
}

// workflow reads the month's country budget and what the page shows of it.
func (s *Service) workflow(ctx context.Context, fy, month int) (workflow, error) {
	w := workflow{month: month, status: "draft_generated"}
	key := monthKey(fy, month)
	err := s.db.QueryRow(ctx, `
		SELECT id, status, COALESCE(total_amount, 0), COALESCE(operational_activity_requirement, 0)
		FROM monthly_work_plan_budget WHERE country_id = $1 AND month_key = $2`,
		rules.Country.HomeCountryID, key,
	).Scan(&w.id, &w.status, &w.total, &w.operationalRequirement)
	switch {
	case err == pgx.ErrNoRows:
	case err != nil:
		return w, fmt.Errorf("budgetpage: reading the month's budget: %w", err)
	default:
		w.exists = true
	}
	if !w.locked() {
		// _recompute_if_live: the request is the month's planned cost.
		live, err := s.monthProgramTotal(ctx, fy, month)
		if err != nil {
			return w, err
		}
		w.total, w.operationalRequirement = live, live
	}
	var prior *string
	err = s.db.QueryRow(ctx, `
		SELECT month_key FROM monthly_work_plan_budget
		WHERE fy = $1 AND status = 'submitted_to_rvp' AND month_key < $2
		ORDER BY month_key DESC LIMIT 1`, fmt.Sprint(fy), key).Scan(&prior)
	if err != nil && err != pgx.ErrNoRows {
		return w, fmt.Errorf("budgetpage: reading the pending months: %w", err)
	}
	if prior != nil {
		w.priorPending = *prior
		var y, m int
		if _, err := fmt.Sscanf(*prior, "%d-%d", &y, &m); err == nil && m >= 1 && m <= 12 {
			w.priorPending = rules.Country.Months[m]
		}
	}
	if w.rec, err = s.reconcile(ctx, key); err != nil {
		return w, err
	}
	return w, nil
}

// monthProgramTotal is _program_source's program total: the month's valid
// lines of the year's ledger.
func (s *Service) monthProgramTotal(ctx context.Context, fy, month int) (int64, error) {
	year := fy
	if month >= 10 {
		year = fy - 1
	}
	start := date(year, time.Month(month), 1)
	end := start.AddDate(0, 1, -1)
	var total int64
	err := s.db.QueryRow(ctx, `
		SELECT COALESCE(sum(l.amount), 0)
		FROM activity_schedule_cost_line l JOIN activity a ON a.id = l.activity_id
		WHERE a.deleted_at IS NULL AND l.fiscal_year = $1
		  AND (a.scheduled_date IS NOT NULL OR a.planned_date IS NOT NULL)
		  AND (a.status IS NULL OR NOT (a.status = ANY($2)))
		  AND (l.planned_date BETWEEN $3 AND $4 OR (l.planned_date IS NULL AND l.month = ANY($5)))`,
		fmt.Sprint(fy), rules.NonFundableStatuses, start, end, wholeMonths(start, end)).Scan(&total)
	if err != nil {
		return 0, fmt.Errorf("budgetpage: totalling the month's plan: %w", err)
	}
	return total, nil
}

// reconcile is reconcile_month's figures the page shows: the advances whose
// activity falls in the month (by planned date, else by when they were
// raised), all committed, and the money of those whose money has moved.
func (s *Service) reconcile(ctx context.Context, key string) (reconciliation, error) {
	var y, m int
	if _, err := fmt.Sscanf(key, "%d-%d", &y, &m); err != nil {
		return reconciliation{}, fmt.Errorf("budgetpage: the month key %q: %w", key, err)
	}
	start := time.Date(y, time.Month(m), 1, 0, 0, 0, 0, zone)
	end := start.AddDate(0, 1, 0)
	var r reconciliation
	err := s.db.QueryRow(ctx, `
		SELECT COALESCE(sum(amount), 0),
		       COALESCE(sum(disbursed_amount) FILTER (WHERE status = ANY($3)), 0),
		       COALESCE(sum(accounted_amount) FILTER (WHERE status = ANY($3)), 0),
		       COALESCE(sum(returned_amount) FILTER (WHERE status = ANY($3)), 0),
		       COALESCE(sum(reimbursed_amount) FILTER (WHERE status = ANY($3)), 0)
		FROM advance_request
		WHERE (planned_date >= $1 AND planned_date < $2)
		   OR (planned_date IS NULL AND created_at >= $1 AND created_at < $2)`,
		start, end, rules.Country.MoneyMovedStatuses,
	).Scan(&r.committed, &r.disbursed, &r.accounted, &r.returned, &r.reimbursed)
	if err != nil {
		return r, fmt.Errorf("budgetpage: reconciling the month: %w", err)
	}
	return r, nil
}

func (s *Service) financeHealth(ctx context.Context, fy int) (financeHealth, error) {
	var f financeHealth
	c := rules.Country.Finance
	err := s.db.QueryRow(ctx, `
		SELECT COALESCE(sum(r.amount), 0),
		       COALESCE(sum(r.amount) FILTER (WHERE r.status = ANY($2)), 0),
		       COALESCE(sum(r.amount) FILTER (WHERE r.status = ANY($3)), 0),
		       COALESCE(sum(r.disbursed_amount) FILTER (WHERE r.status = ANY($4)), 0),
		       COALESCE(sum(r.accounted_amount) FILTER (WHERE r.status = ANY($5)), 0),
		       COALESCE(sum(r.returned_amount), 0),
		       COALESCE(sum(r.amount) FILTER (WHERE a.quarter = 'Q1'), 0),
		       COALESCE(sum(r.amount) FILTER (WHERE a.quarter = 'Q2'), 0),
		       COALESCE(sum(r.amount) FILTER (WHERE a.quarter = 'Q3'), 0),
		       COALESCE(sum(r.amount) FILTER (WHERE a.quarter = 'Q4'), 0)
		FROM advance_request r JOIN activity a ON a.id = r.activity_id
		WHERE a.fy = $1 AND a.deleted_at IS NULL`,
		fmt.Sprint(fy), c.Pending, c.Confirmed, c.Disbursed, c.Accounted,
	).Scan(&f.requested, &f.pending, &f.confirmed, &f.disbursed, &f.accounted, &f.returned,
		&f.quarters[0], &f.quarters[1], &f.quarters[2], &f.quarters[3])
	if err != nil {
		return f, fmt.Errorf("budgetpage: reading the year's advances: %w", err)
	}
	return f, nil
}

func (s *Service) districts(ctx context.Context) ([]district, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM district ORDER BY name, id`)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the districts: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (district, error) {
		var d district
		err := row.Scan(&d.id, &d.name)
		return d, err
	})
}

func isCD(role string) bool  { return slices.Contains(rules.Country.CDRoles, role) }
func isRVP(role string) bool { return slices.Contains(rules.Country.RVPRoles, role) }
