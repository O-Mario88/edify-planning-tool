package weeklyrequest

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/disbursements"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// view is everything the page draws.
type view struct {
	p                              auth.Principal
	r                              role
	a                              ask
	base                           scope
	fy, quarter, monthName         string
	year, month                    int
	weeks                          []time.Time // each week's Monday
	weekStart, weekEnd, today      time.Time
	thisMonth, lastMonth           int64
	awaiting, approved, ready      tally
	returned, pendingAcct          tally
	active                         *weekRequest
	owner, canApprove, canDisburse bool
	statusLabel                    string
	ledger                         []*screensv1.PageRow
	mission                        *mission
	sources                        []source
	insights                       insights
	breakdown                      [4]tally
	districts, staffOptions        [][2]string
	teamTabs                       [][3]string // id, name, active
	showTeamFilters                bool
	ownerButtons                   bool
	// receiptPlans are the reader's disbursed monthly plans waiting for
	// their receipt (budget_views: receipt_pending_plans), drawn only when
	// Go saves the confirmation.
	receiptPlans []receiptPlan
}

// receiptPlan is one disbursed monthly fund plan.
type receiptPlan struct{ id, period, method, reference string }

// mission is _mission_status_for_cceo: how vendor-paid costs are handled.
type mission struct {
	transportDays, nights int
	confirmed             bool
}

// source is one of the week's source activities.
type source struct {
	kind, title, date, location, purpose, status string
}

// insights is the Fund Request Insights panel.
type insights struct {
	week                                 tally
	attention, selfFunded, missingCosted int
	dueHeading, dueDate, dueTiming       string
	action, actionDesc                   string
	takeAction                           bool
}

func monthNumber(name string) (int, bool) {
	for i, m := range months {
		if i > 0 && strings.EqualFold(m, name) {
			return i, true
		}
	}
	return 0, false
}

// weeksOf is get_weeks_of_month: every Monday-first week touching the month.
func weeksOf(year, month int) []time.Time {
	first := time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
	last := first.AddDate(0, 1, -1)
	out := []time.Time{}
	for w := monday(first); !w.After(last); w = w.AddDate(0, 0, 7) {
		out = append(out, w)
	}
	return out
}

func quarterOf(month int) string {
	switch {
	case month >= 10:
		return "Q1"
	case month <= 3:
		return "Q2"
	case month <= 6:
		return "Q3"
	}
	return "Q4"
}

// latestScheduled is the newest scheduled activity in view (of the year when
// fy is given, else of the local month), as a Kampala date.
func (s *Service) latestScheduled(ctx context.Context, v *view, fy string, month int) (*time.Time, error) {
	q := args{}
	where := v.base.activities(v.a, &q) + " AND a.scheduled_date IS NOT NULL"
	if fy != "" {
		where += " AND a.fy = " + q.add(fy)
	} else {
		where += fmt.Sprintf(" AND EXTRACT(MONTH FROM a.scheduled_date AT TIME ZONE 'Africa/Kampala') = %d", month)
	}
	var at *time.Time
	err := s.db.QueryRow(ctx, `SELECT (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date FROM activity a WHERE `+
		where+` ORDER BY a.scheduled_date DESC LIMIT 1`, q...).Scan(&at)
	if err != nil && err.Error() != "no rows in result set" {
		return nil, fmt.Errorf("weeklyrequest: reading the latest work: %w", err)
	}
	return at, nil
}

// pickMonth and pickWeek are the page's defaults: the month and week asked,
// else today's when the page is on the running year, else the newest
// scheduled work's.
func (s *Service) pickMonth(ctx context.Context, v *view, currentFY string) error {
	v.monthName = v.a.monthName
	switch {
	case v.monthName != "":
		m, ok := monthNumber(v.monthName)
		if !ok {
			m = int(v.today.Month())
		}
		v.month = m
	case v.fy == currentFY:
		v.month = int(v.today.Month())
		v.monthName = months[v.month]
	default:
		at, err := s.latestScheduled(ctx, v, v.fy, 0)
		if err != nil {
			return err
		}
		v.month = int(v.today.Month())
		if at != nil {
			v.month = int(at.Month())
		}
		v.monthName = months[v.month]
	}
	fy, _ := strconv.Atoi(v.fy)
	v.year = fy
	if v.month >= 10 {
		v.year = fy - 1
	}
	v.quarter = v.a.quarter
	if v.quarter == "" {
		v.quarter = quarterOf(v.month)
	}
	v.weeks = weeksOf(v.year, v.month)
	return nil
}

func (s *Service) pickWeek(ctx context.Context, v *view, currentFY string) error {
	var start time.Time
	if v.a.week != "" {
		d, err := time.Parse(time.DateOnly, v.a.week)
		if err != nil {
			return errPassOn
		}
		start = d
	}
	if start.IsZero() && v.fy == currentFY && v.month == int(v.today.Month()) {
		start = monday(v.today)
	}
	if start.IsZero() {
		at, err := s.latestScheduled(ctx, v, "", v.month)
		if err != nil {
			return err
		}
		switch {
		case at != nil:
			start = monday(*at)
		case len(v.weeks) > 0:
			start = v.weeks[0]
		default:
			start = v.today
		}
	}
	v.weekStart = monday(start)
	v.weekEnd = v.weekStart.AddDate(0, 0, 6)
	return nil
}

// roundHalfUp is Decimal.quantize(1, ROUND_HALF_UP).
func roundHalfUp(x float64) int64 {
	if x < 0 {
		return -int64(math.Floor(-x + 0.5))
	}
	return int64(math.Floor(x + 0.5))
}

func (s *Service) build(ctx context.Context, p auth.Principal, r role, a ask, now time.Time) (*screensv1.GetPageResponse, error) {
	v := &view{p: p, r: r, a: a, fy: a.fy, today: day(now.In(kampala)), ownerButtons: s.ownerButtons}
	if s.ownerButtons {
		plans, err := s.receiptPending(ctx, p.UserID)
		if err != nil {
			return nil, err
		}
		v.receiptPlans = plans
	}
	currentFY := strconv.Itoa(v.today.Year())
	if v.today.Month() >= time.October {
		currentFY = strconv.Itoa(v.today.Year() + 1)
	}
	sc, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, fmt.Errorf("weeklyrequest: resolving the scope: %w", err)
	}
	if v.base, err = s.scopeFor(ctx, p, sc, a, v.fy); err != nil {
		return nil, err
	}
	v.showTeamFilters = sc.CountryScope || len(sc.SupervisedStaffIDs) > 0
	if err := s.pickMonth(ctx, v, currentFY); err != nil {
		return nil, err
	}
	if err := s.pickWeek(ctx, v, currentFY); err != nil {
		return nil, err
	}
	if err := s.figures(ctx, v, p, sc); err != nil {
		return nil, err
	}
	writes, err := s.selfHealWrites(ctx, p.UserID, p.StaffProfileID, v.base, a, v.weekStart)
	if err != nil {
		return nil, err
	}
	if writes {
		return nil, errPassOn
	}
	if err := s.request(ctx, v, p, sc); err != nil {
		return nil, err
	}
	if err := s.rest(ctx, v, p, sc); err != nil {
		return nil, err
	}
	return page(v), nil
}

// figures is the month's request figures.
func (s *Service) figures(ctx context.Context, v *view, p auth.Principal, sc schooldirectory.Scope) error {
	this, err := s.monthRequests(ctx, v.base, v.a, v.year, v.month, nil, "")
	if err != nil {
		return err
	}
	v.thisMonth = this.total
	anchor := time.Date(v.year, time.Month(v.month), 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, -1)
	prevFY := schooldirectory.OperationalFY(anchor)
	prev, err := s.scopeFor(ctx, p, sc, v.a, prevFY)
	if err != nil {
		return err
	}
	last, err := s.monthRequests(ctx, prev, v.a, anchor.Year(), int(anchor.Month()), nil, "")
	if err != nil {
		return err
	}
	v.lastMonth = last.total
	for _, f := range []struct {
		into     *tally
		statuses []string
		extra    string
	}{
		{&v.awaiting, []string{"submitted_to_pl", "submitted_to_cd"}, ""},
		{&v.approved, []string{"confirmed_for_advance", "disbursed"}, ""},
		{&v.ready, []string{"confirmed_for_advance"}, ""},
		{&v.returned, []string{"returned_by_pl", "returned_by_cd", "returned_by_accountant"}, ""},
		{&v.pendingAcct, []string{"disbursed"}, " AND w.accounted_amount IS NULL"},
	} {
		t, err := s.monthRequests(ctx, v.base, v.a, v.year, v.month, f.statuses, f.extra)
		if err != nil {
			return err
		}
		*f.into = t
	}
	return nil
}

// request is the week's request, what the reader may do with it and its
// submitted ledger; a week with costed lines and no request is handed on.
func (s *Service) request(ctx context.Context, v *view, p auth.Principal, sc schooldirectory.Scope) error {
	weekScope := v.base
	weekFY := schooldirectory.OperationalFY(v.weekStart)
	if weekFY != v.fy && schooldirectory.OperationalFY(v.weekEnd) == v.fy {
		ws, err := s.scopeFor(ctx, p, sc, v.a, weekFY)
		if err != nil {
			return err
		}
		weekScope = ws
	}
	active, err := s.weekRequest(ctx, weekScope, v.a, v.weekStart)
	if errors.Is(err, errMany) {
		return errPassOn
	}
	if err != nil {
		return err
	}
	if active == nil {
		costed, err := s.costedWeek(ctx, v, p)
		if err != nil {
			return err
		}
		if costed {
			// The card draws the week's budget workspace: handed on.
			return errPassOn
		}
		return nil
	}
	v.active = active
	v.owner = active.owner == p.UserID
	v.statusLabel = disbursements.WeeklyStatus(active.status, active.pendingAccountability, active.submittedAccountability, active.reviewed)
	v.canDisburse = active.status == "confirmed_for_advance" && v.r.PaymentAct
	if (active.status == "submitted_to_pl" || active.status == "submitted_to_cd") && !v.owner {
		switch {
		case v.r.ClearsEscalated:
			v.canApprove = true
		case active.status == "submitted_to_pl" && p.ActiveRole == "Program Lead":
			if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM staff_supervisor_assignment a
JOIN staff_profile sup ON sup.id = a.supervisor_id JOIN staff_profile sub ON sub.id = a.supervisee_id
WHERE sup.user_id = $1 AND sub.user_id = $2)`, p.UserID, active.owner).Scan(&v.canApprove); err != nil {
				return fmt.Errorf("weeklyrequest: reading the supervision: %w", err)
			}
		}
	}
	var pendingClaims bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM advance_request r JOIN weekly_fund_request_line l
ON l.activity_budget_line_id = r.budget_line_id WHERE l.weekly_fund_request_id = $1
AND r.status IN ('accountability_pl_pending', 'reimbursement_pl_pending'))`, active.id).Scan(&pendingClaims); err != nil {
		return fmt.Errorf("weeklyrequest: reading the accountability awaiting approval: %w", err)
	}
	if pendingClaims || active.status == "disbursed" {
		// The accountability approvals and the receipt and accountability
		// steps: not drawn here yet.
		return errPassOn
	}
	rows, ok, err := budgetpage.WeeklyRequestLedger(ctx, s.db, active.id)
	if err != nil {
		return err
	}
	if !ok {
		return errPassOn
	}
	v.ledger = rows
	return nil
}

// rest is the mission status, the week's source activities, the insights,
// the totals by period and the filters' and tabs' options.
func (s *Service) rest(ctx context.Context, v *view, p auth.Principal, sc schooldirectory.Scope) error {
	for _, step := range []func(context.Context, *view, auth.Principal, schooldirectory.Scope) error{
		s.readMission, s.readSources, s.readInsights, s.readBreakdown, s.readOptions,
	} {
		if err := step(ctx, v, p, sc); err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) readBreakdown(ctx context.Context, v *view, _ auth.Principal, _ schooldirectory.Scope) error {
	week, err := s.between(ctx, v.base, v.a, v.weekStart, v.weekStart, true)
	if err != nil {
		return err
	}
	month, err := s.monthRequests(ctx, v.base, v.a, v.year, v.month, nil, "")
	if err != nil {
		return err
	}
	qFrom, qTo := targets.QuarterRange(v.fy, v.quarter)
	quarter, err := s.between(ctx, v.base, v.a, qFrom, qTo, false)
	if err != nil {
		return err
	}
	fFrom, fTo := targets.FYRange(v.fy)
	year, err := s.between(ctx, v.base, v.a, fFrom, fTo, false)
	if err != nil {
		return err
	}
	v.breakdown = [4]tally{week, month, quarter, year}
	return nil
}

// staffMoney leaves out partner-delivered work, which a partner is paid for
// directly and the card's workspace never shows (exclude_partner).
const staffMoney = `l.partner_id IS NULL AND a.delivery_type IS DISTINCT FROM 'partner'`

// costedWeek is whether the week holds a cost line the card's budget
// workspace could show: one owned by, or on an activity of (run or
// monitored by), the person the page is on — the pinned staff, else the
// reader — or any line at all for a country reader asking for everyone. A
// superset of the workspace's lines, so an empty answer means an empty card.
func (s *Service) costedWeek(ctx context.Context, v *view, p auth.Principal) (bool, error) {
	from, to := v.weekStart, v.weekEnd.AddDate(0, 0, 1)
	var costed bool
	if v.base.country && v.base.staff == "" {
		err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity_schedule_cost_line l
LEFT JOIN activity a ON a.id = l.activity_id
WHERE l.planned_date >= $1 AND l.planned_date < $2 AND `+staffMoney+`)`, from, to).Scan(&costed)
		if err != nil {
			return false, fmt.Errorf("weeklyrequest: reading the week's costs: %w", err)
		}
		return costed, nil
	}
	who := v.base.staff
	if who == "" {
		who = p.UserID
	}
	err := s.db.QueryRow(ctx, `
WITH ids AS (SELECT $3::text AS id UNION SELECT sp.id FROM staff_profile sp WHERE sp.user_id = $3)
SELECT EXISTS (SELECT 1 FROM activity_schedule_cost_line l LEFT JOIN activity a ON a.id = l.activity_id
WHERE l.planned_date >= $1 AND l.planned_date < $2 AND `+staffMoney+`
  AND (l.responsible_user IN (SELECT id FROM ids) OR a.responsible_staff_id IN (SELECT id FROM ids)
       OR a.monitored_by_staff_id IN (SELECT id FROM ids)))`, from, to, who).Scan(&costed)
	if err != nil {
		return false, fmt.Errorf("weeklyrequest: reading the week's costs: %w", err)
	}
	return costed, nil
}

// receiptPending is receipt_pending_plans: at most three, latest paid first.
func (s *Service) receiptPending(ctx context.Context, userID string) ([]receiptPlan, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(period_key, ''), COALESCE(disburse_method, ''), COALESCE(disburse_reference, '')
  FROM fund_request WHERE submitted_by_user_id = $1 AND period = 'monthly' AND status = 'disbursed'
   AND receipt_confirmed_at IS NULL ORDER BY disbursed_at DESC NULLS FIRST LIMIT 3`, userID)
	if err != nil {
		return nil, fmt.Errorf("weeklyrequest: reading the plans waiting for receipt: %w", err)
	}
	defer rows.Close()
	var out []receiptPlan
	for rows.Next() {
		var r receiptPlan
		if err := rows.Scan(&r.id, &r.period, &r.method, &r.reference); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
