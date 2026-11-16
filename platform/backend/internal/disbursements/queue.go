package disbursements

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// item is one queue entry (the dicts _monthly_items, _weekly_items,
// _partner_items and _reimbursement_items build).
type item struct {
	key, kind, kindLabel, name, subtitle, status string
	amount                                       int64
	id                                           string
	// owner is the user whose plan the money is (_owner_user_id).
	owner string
	// staffID is the partner work's responsible staff profile.
	staffID string
	// pendingAccountability: a weekly advance with an advance whose
	// accountability waits for review.
	pendingAccountability bool
}

const (
	kindMonthly       = "monthly"
	kindWeekly        = "weekly"
	kindPartner       = "partner"
	kindReimbursement = "reimbursement"
)

// queue reads the month's consolidated queue, sorted, and the names of the
// people it names (names_out).
type queue struct {
	db    schooldirectory.Querier
	names map[string]string
}

func (q *queue) read(ctx context.Context, fy string, month int) ([]item, error) {
	monthly, err := q.monthly(ctx, fy, month)
	if err != nil {
		return nil, err
	}
	weekly, err := q.weekly(ctx, fy, month)
	if err != nil {
		return nil, err
	}
	partner, err := q.partner(ctx)
	if err != nil {
		return nil, err
	}
	reimbursements, err := q.reimbursements(ctx)
	if err != nil {
		return nil, err
	}
	out := append(append(append(monthly, weekly...), partner...), reimbursements...)
	sort.SliceStable(out, func(i, j int) bool {
		a, b := rank(out[i].status), rank(out[j].status)
		if a != b {
			return a < b
		}
		return out[i].amount > out[j].amount
	})
	return out, nil
}

func rank(status string) int {
	if r, ok := rules.StatusSort[status]; ok {
		return r
	}
	return 9
}

// learn is _user_names: each id's name, every account (none is left out),
// added to what the page already knows.
func (q *queue) learn(ctx context.Context, ids []string) error {
	want := []string{}
	for _, id := range ids {
		if id != "" {
			want = append(want, id)
		}
	}
	if len(want) == 0 {
		return nil
	}
	rows, err := q.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, want)
	if err != nil {
		return fmt.Errorf("disbursements: reading names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return fmt.Errorf("disbursements: reading names: %w", err)
		}
		q.names[id] = name
	}
	return rows.Err()
}

func (q *queue) name(id, fallback string) string {
	if n, ok := q.names[id]; ok {
		return n
	}
	return fallback
}

func (q *queue) monthly(ctx context.Context, fy string, month int) ([]item, error) {
	rows, err := q.db.Query(ctx, `
		SELECT id, COALESCE(submitted_by_user_id, ''), COALESCE(submitted_by_role, ''), activity_count,
		       total_amount, status, accountability_submitted_at IS NOT NULL, accountability_reviewed_at IS NOT NULL
		FROM fund_request
		WHERE period = 'monthly' AND fy = $1 AND period_key = $2 AND NOT (status = 'draft')`,
		fy, fy+"-M"+strconv.Itoa(month))
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the monthly plans: %w", err)
	}
	type plan struct {
		id, owner, role, status string
		activities              int
		total                   int64
		submitted, reviewed     bool
	}
	plans, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (plan, error) {
		var p plan
		err := r.Scan(&p.id, &p.owner, &p.role, &p.activities, &p.total, &p.status, &p.submitted, &p.reviewed)
		return p, err
	})
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the monthly plans: %w", err)
	}
	owners := []string{}
	for _, p := range plans {
		owners = append(owners, p.owner)
	}
	if err := q.learn(ctx, owners); err != nil {
		return nil, err
	}
	out := []item{}
	for _, p := range plans {
		label := "Team Fund Plan"
		if p.role == "ProjectCoordinator" {
			label = "Special Project Fund Plan"
		}
		out = append(out, item{
			key: "fr:" + p.id, kind: kindMonthly, kindLabel: label, name: q.name(p.owner, "CCEO"),
			subtitle: fmt.Sprintf("%s %s · %d activities", rules.Months[month], fy, p.activities),
			amount:   p.total, status: monthlyStatus(p.status, p.submitted, p.reviewed), id: p.id, owner: p.owner,
		})
	}
	return out, nil
}

func (q *queue) weekly(ctx context.Context, fy string, month int) ([]item, error) {
	rows, err := q.db.Query(ctx, `
		SELECT w.id, COALESCE(w.responsible_user, ''), w.week_start_date, w.week_end_date, w.total_amount, w.status,
		       w.accountability_submitted_at IS NOT NULL, w.accountability_reviewed_at IS NOT NULL,
		       EXISTS (SELECT 1 FROM weekly_fund_request_line s
		               JOIN advance_request r ON r.budget_line_id = s.activity_budget_line_id
		               WHERE s.weekly_fund_request_id = w.id AND r.status = 'accountability_pending')
		FROM weekly_fund_request w
		WHERE w.fy = $1 AND EXTRACT(MONTH FROM w.week_start_date) = $2
		  AND NOT (w.status IN ('not_requested', 'cancelled'))`, fy, month)
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the weekly advances: %w", err)
	}
	type advance struct {
		id, owner, status            string
		start, end                   time.Time
		total                        int64
		submitted, reviewed, pending bool
	}
	advances, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (advance, error) {
		var a advance
		err := r.Scan(&a.id, &a.owner, &a.start, &a.end, &a.total, &a.status, &a.submitted, &a.reviewed, &a.pending)
		return a, err
	})
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the weekly advances: %w", err)
	}
	owners := []string{}
	for _, a := range advances {
		owners = append(owners, a.owner)
	}
	if err := q.learn(ctx, owners); err != nil {
		return nil, err
	}
	out := []item{}
	for _, a := range advances {
		out = append(out, item{
			key: "wfr:" + a.id, kind: kindWeekly, kindLabel: "Weekly Advance", name: q.name(a.owner, "Staff"),
			subtitle: "Week " + shortDay(a.start) + " – " + shortDay(a.end),
			amount:   a.total, status: weeklyStatus(a.status, a.pending, a.submitted, a.reviewed), id: a.id, owner: a.owner,
			pendingAccountability: a.pending,
		})
	}
	return out, nil
}

// partner is _partner_items: verified partner work awaiting payment, newest
// first, at most 200, whatever the month.
func (q *queue) partner(ctx context.Context) ([]item, error) {
	rows, err := q.db.Query(ctx, `
		SELECT a.id, COALESCE(p.name, ''), p.id IS NOT NULL, a.school_id IS NOT NULL, COALESCE(s.name, ''),
		       COALESCE(a.activity_type, ''), COALESCE(a.responsible_staff_id, ''),
		       COALESCE((SELECT SUM(l.amount) FROM activity_schedule_cost_line l WHERE l.activity_id = a.id), 0)
		FROM activity a
		LEFT JOIN partner p ON p.id = a.assigned_partner_id AND p.deleted_at IS NULL
		LEFT JOIN school s ON s.id = a.school_id
		WHERE a.deleted_at IS NULL AND a.delivery_type = 'partner' AND a.status = 'ia_verified'
		  AND a.payment_status = ANY($1)
		ORDER BY a.created_at DESC
		LIMIT 200`, rules.PartnerPayableStatuses)
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the partner payments: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (item, error) {
		var it item
		var partnerName, schoolName, activityType string
		var known, atSchool bool
		if err := r.Scan(&it.id, &partnerName, &known, &atSchool, &schoolName, &activityType, &it.staffID, &it.amount); err != nil {
			return it, err
		}
		it.key, it.kind, it.kindLabel, it.status = "act:"+it.id, kindPartner, "Partner Payment", pendingDisbursement
		it.name = "Partner"
		if known {
			it.name = partnerName
		}
		it.subtitle = activityTypeLabel(activityType)
		if atSchool {
			it.subtitle = schoolName
		}
		return it, nil
	})
}

// reimbursements is _reimbursement_items: submitted self-funded claims,
// newest first, at most 25.
func (q *queue) reimbursements(ctx context.Context) ([]item, error) {
	rows, err := q.db.Query(ctx, `
		SELECT r.id, COALESCE(r.responsible_user_id, ''), r.amount, COALESCE(a.activity_type, '')
		FROM advance_request r
		JOIN activity a ON a.id = r.activity_id
		WHERE r.status = 'reimbursement_submitted'
		ORDER BY r.created_at DESC
		LIMIT 25`)
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the reimbursement claims: %w", err)
	}
	type claim struct {
		id, owner, activityType string
		amount                  int64
	}
	claims, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (claim, error) {
		var c claim
		err := r.Scan(&c.id, &c.owner, &c.amount, &c.activityType)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("disbursements: reading the reimbursement claims: %w", err)
	}
	owners := []string{}
	for _, c := range claims {
		owners = append(owners, c.owner)
	}
	if err := q.learn(ctx, owners); err != nil {
		return nil, err
	}
	out := []item{}
	for _, c := range claims {
		out = append(out, item{
			key: "adv:" + c.id, kind: kindReimbursement, kindLabel: "Reimbursement", name: q.name(c.owner, "Staff"),
			subtitle: activityTypeLabel(c.activityType), amount: c.amount, status: pendingDisbursement, id: c.id,
		})
	}
	return out, nil
}

// shortDay is Python's "%b %-d": Nov 2.
func shortDay(d time.Time) string { return d.Format("Jan 2") }

// busiestMonth is the month of the year's first monthly plan (by id), the
// month the page opens on when its own is empty and none was asked for.
func busiestMonth(ctx context.Context, db schooldirectory.Querier, fy string) (int, error) {
	var key string
	err := db.QueryRow(ctx, `SELECT period_key FROM fund_request WHERE period = 'monthly' AND fy = $1 ORDER BY id LIMIT 1`, fy).Scan(&key)
	if err == pgx.ErrNoRows {
		return 0, nil
	}
	if err != nil {
		return 0, fmt.Errorf("disbursements: reading the year's plans: %w", err)
	}
	i := strings.LastIndex(key, "M")
	if i < 0 {
		return 0, nil
	}
	m, err := strconv.Atoi(strings.TrimSpace(key[i+1:]))
	if err != nil {
		return 0, nil
	}
	return m, nil
}
