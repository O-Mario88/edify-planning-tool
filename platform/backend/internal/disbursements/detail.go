package disbursements

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// breakdownPageSize is TABLE_PAGE_SIZE: the rows one page of a breakdown
// holds.
const breakdownPageSize = 50

const approvalHint = "Disbursement unlocks once the approval chain is complete."

// mix is the month's money by where it goes, in the order the dashboard
// first meets each label (mix_tot).
type mix struct {
	labels []string
	totals map[string]int64
}

func (m *mix) add(label string, amount int64) {
	if _, ok := m.totals[label]; !ok {
		m.labels = append(m.labels, label)
	}
	m.totals[label] += amount
}

// mixOf is the disbursement mix over the whole queue: each monthly plan's
// categories, each weekly advance's line groups, the partner payments and
// the reimbursements.
func mixOf(ctx context.Context, db schooldirectory.Querier, queue []item) (*mix, error) {
	plans, weeks := []string{}, []string{}
	for _, it := range queue {
		switch it.kind {
		case kindMonthly:
			plans = append(plans, it.id)
		case kindWeekly:
			weeks = append(weeks, it.id)
		}
	}
	planCats, err := planCategories(ctx, db, plans)
	if err != nil {
		return nil, err
	}
	weekGroups, err := weekLineGroups(ctx, db, weeks)
	if err != nil {
		return nil, err
	}
	m := &mix{totals: map[string]int64{}}
	for _, it := range queue {
		switch it.kind {
		case kindMonthly:
			for _, c := range planCats[it.id] {
				m.add(c.label, c.total)
			}
		case kindWeekly:
			for _, g := range weekGroups[it.id] {
				m.add(g.label, g.total)
			}
		case kindPartner:
			m.add("Partner Payments", it.amount)
		default:
			m.add("Reimbursements", it.amount)
		}
	}
	return m, nil
}

type labelled struct {
	label string
	total int64
}

// planCategories is _monthly_detail's breakdown for each plan: its items'
// cost lines by category, in the categories' order.
func planCategories(ctx context.Context, db schooldirectory.Querier, plans []string) (map[string][]labelled, error) {
	out := map[string][]labelled{}
	if len(plans) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
		SELECT i.fund_request_id, COALESCE(a.activity_type, ''), COALESCE(a.delivery_type, ''), l.amount
		FROM fund_request_item i
		JOIN activity_schedule_cost_line l ON l.id = i.activity_schedule_cost_line_id
		JOIN activity a ON a.id = l.activity_id
		WHERE i.fund_request_id = ANY($1)`, plans)
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the plans' cost lines: %w", err)
	}
	sums := map[string]map[string]int64{}
	err = forEach(rows, func(r pgx.Rows) error {
		var plan, activityType, delivery string
		var amount int64
		if err := r.Scan(&plan, &activityType, &delivery, &amount); err != nil {
			return err
		}
		if sums[plan] == nil {
			sums[plan] = map[string]int64{}
		}
		sums[plan][category(activityType, delivery, "")] += amount
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the plans' cost lines: %w", err)
	}
	for plan, byCat := range sums {
		for _, c := range rules.CategoryOrder {
			if total, ok := byCat[c]; ok {
				out[plan] = append(out[plan], labelled{label: c, total: total})
			}
		}
	}
	return out, nil
}

// weekLineGroups is _weekly_detail's breakdown for each advance: its lines
// by label, largest first.
func weekLineGroups(ctx context.Context, db schooldirectory.Querier, weeks []string) (map[string][]labelled, error) {
	out := map[string][]labelled{}
	if len(weeks) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
		SELECT weekly_fund_request_id, line_item_type, total_cost
		FROM weekly_fund_request_line WHERE weekly_fund_request_id = ANY($1)`, weeks)
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the advances' lines: %w", err)
	}
	err = forEach(rows, func(r pgx.Rows) error {
		var week, kind string
		var total int64
		if err := r.Scan(&week, &kind, &total); err != nil {
			return err
		}
		label, ok := rules.LineTypeLabels[kind]
		if !ok {
			label = budgetpage.PyTitle(strings.ReplaceAll(kind, "_", " "))
		}
		groups := out[week]
		i := slices.IndexFunc(groups, func(g labelled) bool { return g.label == label })
		if i < 0 {
			out[week] = append(groups, labelled{label: label, total: total})
		} else {
			groups[i].total += total
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the advances' lines: %w", err)
	}
	for _, groups := range out {
		sort.SliceStable(groups, func(i, j int) bool { return groups[i].total > groups[j].total })
	}
	return out, nil
}

func forEach(rows pgx.Rows, each func(pgx.Rows) error) error {
	defer rows.Close()
	for rows.Next() {
		if err := each(rows); err != nil {
			return err
		}
	}
	return rows.Err()
}

// detailTable is partials/disbursements/detail.html (fund_detail.html) as
// the feed reads it: the item's name and kind, its action row's words, the
// approval hint under it, and the ledger or the breakdown. ok is false when
// the ledger or breakdown runs past one page.
func detailTable(ctx context.Context, db schooldirectory.Querier, it item) (*screensv1.PageBlock, bool, error) {
	t := &screensv1.PageTable{Title: it.name + " — " + it.kindLabel}
	var ok bool
	var err error
	switch it.kind {
	case kindMonthly:
		var lines []string
		if lines, err = planLines(ctx, db, it.id); err == nil {
			t.Rows, ok, err = budgetpage.CostLineLedger(ctx, db, lines)
		}
	case kindWeekly:
		t.Rows, ok, err = budgetpage.WeeklyRequestLedger(ctx, db, it.id)
	default:
		t.Columns = []*screensv1.PageColumn{{Label: "Activity Category"}, {Label: "Planned Qty"},
			{Label: "Unit Cost (UGX)"}, {Label: "Total (UGX)"}}
		t.Rows, ok, err = breakdown(ctx, db, it)
	}
	if err != nil || !ok {
		return nil, ok, err
	}
	words, err := actionWords(ctx, db, it)
	if err != nil {
		return nil, false, err
	}
	t.Subtitle = strings.Join(words, " ")
	if it.status == pendingApproval {
		t.Footnote = approvalHint
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, true, nil
}

func planLines(ctx context.Context, db schooldirectory.Querier, plan string) ([]string, error) {
	rows, err := db.Query(ctx, `SELECT activity_schedule_cost_line_id FROM fund_request_item WHERE fund_request_id = $1`, plan)
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the plan's items: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the plan's items: %w", err)
	}
	return ids, nil
}

// breakdown is _partner_detail's and _reimb_detail's table body.
func breakdown(ctx context.Context, db schooldirectory.Querier, it item) ([]*screensv1.PageRow, bool, error) {
	out := []*screensv1.PageRow{}
	if it.kind == kindPartner {
		rows, err := db.Query(ctx, `
			SELECT COALESCE(label, ''), quantity, unit_cost, amount
			FROM activity_schedule_cost_line WHERE activity_id = $1`, it.id)
		if err != nil {
			return nil, false, fmt.Errorf("disbursements: reading the partner work's lines: %w", err)
		}
		err = forEach(rows, func(r pgx.Rows) error {
			var label string
			var qty, unit, amount int64
			if err := r.Scan(&label, &qty, &unit, &amount); err != nil {
				return err
			}
			out = append(out, breakdownRow(label, qty, unit, amount))
			return nil
		})
		if err != nil {
			return nil, false, fmt.Errorf("disbursements: reading the partner work's lines: %w", err)
		}
	} else {
		var amount int64
		var accounted *int64
		if err := db.QueryRow(ctx, `SELECT amount, accounted_amount FROM advance_request WHERE id = $1`, it.id).
			Scan(&amount, &accounted); err != nil {
			return nil, false, fmt.Errorf("disbursements: reading the claim: %w", err)
		}
		out = append(out, breakdownRow("Approved budget", 1, amount, amount))
		if accounted != nil {
			out = append(out, breakdownRow("Actual spend (claimed)", 1, *accounted, *accounted))
		}
	}
	if len(out) > breakdownPageSize {
		return nil, false, nil
	}
	if len(out) == 0 {
		out = append(out, row("No budget lines behind this item."))
	}
	return out, true, nil
}

func breakdownRow(label string, qty, unit, total int64) *screensv1.PageRow {
	q := "—"
	if qty != 0 {
		q = strconv.FormatInt(qty, 10)
	}
	return row(label, q, budgetpage.UGX(unit), budgetpage.UGX(total))
}

func row(texts ...string) *screensv1.PageRow {
	r := &screensv1.PageRow{}
	for _, t := range texts {
		r.Cells = append(r.Cells, &screensv1.PageCell{Text: t})
	}
	return r
}

// actionWords is partials/disbursements/_actions.html read as words: the
// approval hint, then each action the item is given, in the row's order.
func actionWords(ctx context.Context, db schooldirectory.Querier, it item) ([]string, error) {
	words := []string{}
	if it.status == pendingApproval {
		words = append(words, approvalHint)
	}
	owner, err := planOwner(ctx, db, it)
	if err != nil {
		return nil, err
	}
	monthly := it.kind == kindMonthly
	ready := it.status == pendingDisbursement
	for _, a := range []struct {
		shown bool
		label string
	}{
		{owner != "", "View Full Plan"},
		{it.kind == kindWeekly && it.pendingAccountability, "Review Accountability"},
		{ready && monthly, "Disburse"},
		{ready && it.kind == kindWeekly, "Disburse Advance"},
		{it.kind == kindPartner, "Pay Partner"},
		{it.kind == kindReimbursement, "Process Reimbursement"},
		{(ready || it.status == held) && monthly, "Return"},
		{ready && monthly, "Hold"},
		{it.status == held, "Release Hold"},
		{true, "Download Voucher"},
	} {
		if a.shown {
			words = append(words, a.label)
		}
	}
	return words, nil
}

// planOwner is _owner_user_id: the plan's submitter, the advance's owner,
// the user of the partner work's responsible (live) staff profile; a claim
// names none.
func planOwner(ctx context.Context, db schooldirectory.Querier, it item) (string, error) {
	switch it.kind {
	case kindMonthly, kindWeekly:
		return it.owner, nil
	case kindPartner:
		if it.staffID == "" {
			return "", nil
		}
		var user string
		err := db.QueryRow(ctx, `SELECT COALESCE(user_id, '') FROM staff_profile WHERE id = $1 AND deleted_at IS NULL`, it.staffID).Scan(&user)
		if err == pgx.ErrNoRows {
			return "", nil
		}
		if err != nil {
			return "", fmt.Errorf("disbursements: reading the partner work's owner: %w", err)
		}
		return user, nil
	}
	return "", nil
}
