package budgetpage

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The ledger other pages draw (partials/budgets/budget_group_tables.html
// over apps.budget.services.budget_groups): the Disbursements page draws it
// for the selected monthly plan's live cost lines and for a weekly advance's
// submitted snapshot.

const ledgerColumns = `
	l.activity_id, COALESCE(l.responsible_user, ''), COALESCE(l.cost_setting_key, ''),
	l.planned_date, l.partner_id,
	COALESCE(a.activity_type, ''), COALESCE(a.programme_activity_type, ''), COALESCE(a.delivery_type, ''),
	COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
	COALESCE(a.expected_participants, 0), COALESCE(a.daily_visit_batch_id, '')`

// CostLineLedger is the ledger of the given cost lines, as they stand.
// ok is false when the groups would not fit one page of the ledger.
func CostLineLedger(ctx context.Context, db schooldirectory.Querier, ids []string) (rows []*screensv1.PageRow, ok bool, err error) {
	return ledgerFrom(ctx, db, `
		SELECT COALESCE(l.label, ''), COALESCE(l.line_item_type, ''), COALESCE(l.amount, 0), COALESCE(l.unit_cost, 0),
		       COALESCE(l.quantity, 0), `+ledgerColumns+`
		FROM activity_schedule_cost_line l
		JOIN activity a ON a.id = l.activity_id
		WHERE l.id = ANY($1)`, ids)
}

// WeeklyRequestLedger is weekly_request_budget: the request's submitted
// snapshot (its description, quantity, unit cost, total and line type) over
// the cost line and activity each snapshot line was taken from, never
// repriced.
func WeeklyRequestLedger(ctx context.Context, db schooldirectory.Querier, requestID string) (rows []*screensv1.PageRow, ok bool, err error) {
	return ledgerFrom(ctx, db, `
		SELECT s.description, s.line_item_type, s.total_cost, s.unit_cost, s.quantity, `+ledgerColumns+`
		FROM weekly_fund_request_line s
		JOIN activity_schedule_cost_line l ON l.id = s.activity_budget_line_id
		JOIN activity a ON a.id = l.activity_id
		WHERE s.weekly_fund_request_id = $1`, requestID)
}

func ledgerFrom(ctx context.Context, db schooldirectory.Querier, sql string, arg any) ([]*screensv1.PageRow, bool, error) {
	rs, err := db.Query(ctx, sql, arg)
	if err != nil {
		return nil, false, fmt.Errorf("budgetpage: reading the ledger's lines: %w", err)
	}
	lines, err := pgx.CollectRows(rs, func(row pgx.CollectableRow) (line, error) {
		var l line
		err := row.Scan(&l.label, &l.lineItemType, &l.amount, &l.unitCost, &l.quantity,
			&l.activityID, &l.responsibleUser, &l.settingKey, &l.plannedDate, &l.partnerID,
			&l.activityType, &l.programmeType, &l.deliveryType,
			&l.teachers, &l.leaders, &l.others, &l.expected, &l.batchID)
		return l, err
	})
	if err != nil {
		return nil, false, fmt.Errorf("budgetpage: reading the ledger's lines: %w", err)
	}
	s := &Service{db: db}
	dayRates, err := s.dayRates(ctx, lines)
	if err != nil {
		return nil, false, err
	}
	gs := groups(lines, dayRates)
	if len(gs) > groupsPageSize {
		return nil, false, nil
	}
	if len(gs) == 0 {
		// The ledger's {% empty %} row, then its grand total.
		return []*screensv1.PageRow{
			cells("No costed activities in this period. Schedule activities in My Plan to populate this budget."),
			cells("Grand total", inCurrency(CurrencyFrom(ctx), 0), inCurrency(CurrencyFrom(ctx), 0)),
		}, true, nil
	}
	var staff, total int64
	for _, g := range gs {
		staff += g.staffTotal
		total += g.total
	}
	return ledgerRows(CurrencyFrom(ctx), gs, staff, total), true, nil
}

// CurrencyCode is the ISO code of the money of the country w (the request's
// country): its recorded currency, UGX wherever none is recorded
// (docs/migration/80, §19).
func CurrencyCode(w *country.Work) string {
	if w == nil || w.Currency == "" {
		return "UGX"
	}
	return w.Currency
}

// CurrencyFrom is CurrencyCode of the country the request is made in, read
// from its caller; UGX without one.
func CurrencyFrom(ctx context.Context) string {
	if p, ok := auth.PrincipalFrom(ctx); ok {
		return CurrencyCode(p.Country)
	}
	return "UGX"
}

// In is the ugx filter in the currency code: KES 24,000.
func In(code string, n int64) string { return inCurrency(code, n) }

// CompactIn is format_ugx_compact in the currency code: KES 1.2M.
func CompactIn(code string, n int64) string { return compactIn(code, n) }

// UGX is the ugx template filter: UGX 24,000.
func UGX(n int64) string { return ugx(n) }

// UGXCompact is apps.core.metrics.format_ugx_compact: UGX 1.2M, UGX 850K.
func UGXCompact(n int64) string { return ugxCompact(n) }

// PyTitle is Python's str.title().
func PyTitle(s string) string { return pyTitle(s) }

// Percentage is apps.core.metrics.percentage_or_zero: round(a / b * 100),
// a half to the even whole number, and 0 for an empty denominator.
func Percentage(a, b int64) int64 {
	if b == 0 {
		return 0
	}
	return pyPercentage(a, b)
}
