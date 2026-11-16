package fundapprovals

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	fw "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
)

// errHandOn is a page Go hands on to the existing application.
var errHandOn = errors.New("fundapprovals: handed on")

// monthBlocks is the side panel, the budget mix and the recent decisions.
type monthBlocks struct {
	side, mix, recent *screensv1.PageBlock
}

// month is _workspace_panels: the month's requests (in the calendar year
// named by the financial year's number, as month_bounds reads it), the
// planned money and its mix, and the latest decisions. nil hands the page
// on.
func (s *Service) month(ctx context.Context, a ask, officers []officer, ids []string, awaiting string, now time.Time) (*monthBlocks, error) {
	year, _ := strconv.Atoi(a.fy)
	start := time.Date(year, time.Month(a.month), 1, 0, 0, 0, 0, time.UTC)
	end := start.AddDate(0, 1, -1)
	users := userIDs(officers)
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(status, ''), total_amount FROM weekly_fund_request
		WHERE responsible_user = ANY($1) AND week_start_date >= $2 AND week_start_date <= $3`, users, start, end)
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the month's requests: %w", err)
	}
	var waiting, back, approved int64
	var approvedMoney int64
	monthIDs := []string{}
	err = forEach(rows, func(r pgx.Rows) error {
		var id, status string
		var total int64
		if err := r.Scan(&id, &status, &total); err != nil {
			return err
		}
		monthIDs = append(monthIDs, id)
		switch {
		case status == awaiting:
			waiting++
		case strings.HasPrefix(status, "returned"):
			back++
		case status == "confirmed_for_advance" || status == "disbursed" || status == "accounted" || status == "closed":
			approved++
			approvedMoney += total
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the month's requests: %w", err)
	}

	rows, err = s.db.Query(ctx, `SELECT l.amount, COALESCE(a.activity_type, ''), COALESCE(a.delivery_type, ''),
		COALESCE(a.programme_activity_type, '')`+weekBase+` AND l.month = $3`, ids, a.fy, a.month)
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the month's cost lines: %w", err)
	}
	var planned int64
	labels, totals := []string{}, map[string]int64{}
	err = forEach(rows, func(r pgx.Rows) error {
		var amount int64
		var activityType, delivery, programme string
		if err := r.Scan(&amount, &activityType, &delivery, &programme); err != nil {
			return err
		}
		planned += amount
		c := category(activityType, delivery, programme)
		if _, ok := totals[c]; !ok {
			labels = append(labels, c)
		}
		totals[c] += amount
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the month's cost lines: %w", err)
	}

	subjects := monthIDs
	if len(subjects) == 0 {
		var n int
		if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM weekly_fund_request WHERE responsible_user = ANY($1)`, users).
			Scan(&n); err != nil {
			return nil, fmt.Errorf("fundapprovals: counting the team's requests: %w", err)
		}
		if n > recentFallbackLimit {
			return nil, nil
		}
		if subjects, err = collect(ctx, s.db, `SELECT id FROM weekly_fund_request WHERE responsible_user = ANY($1)`, users); err != nil {
			return nil, err
		}
	}
	recent, err := s.recent(ctx, subjects, now)
	if err != nil {
		return nil, err
	}

	monthName := rules.Months[a.month]
	state := "On Track"
	if waiting > 0 {
		state = fmt.Sprintf("%d waiting", waiting)
	}
	ugx := budgetpage.UGXCompact
	return &monthBlocks{
		side: fw.Side("This Month",
			fw.Progress{
				Title: monthName + " Plan & Budget Approval", Status: state, Allocation: ugx(planned),
				Caption: "Approved (to date)", Approved: ugx(approvedMoney),
				Pct: budgetpage.Percentage(approvedMoney, planned), Link: "/team-planning-oversight/?view=planning",
				LinkLabel: "View approval dashboard",
			},
			fw.Rate{
				Title: "Approval Rate This Month", Subline: "Approval Rate", Empty: "No decisions recorded this month yet.",
				Approved: approved, Returned: back, Pending: waiting,
			}),
		mix:    fw.Mix(fmt.Sprintf("Approval Insights / Budget Mix (%s)", monthName), labels, totals),
		recent: fw.Recent("Recent Approval Activity", recent, ""),
	}, nil
}

// recentLimit is recent_activity's limit; it reads three times as many
// audit rows to find them.
const recentLimit = 3

// recent is fund_workspace.recent_activity: the latest successful approvals
// and returns of these requests, as the officer, the week's month and the
// decision, the request's money and when, in Nairobi's day.
func (s *Service) recent(ctx context.Context, subjects []string, now time.Time) ([]string, error) {
	rows, err := s.db.Query(ctx, `
		SELECT g.action, g.created_at, w.id IS NOT NULL, COALESCE(w.responsible_user, ''), w.week_start_date,
		       COALESCE(NULLIF(w.disbursed_amount, 0), w.total_amount, 0), COALESCE(u.name, ''), u.id IS NOT NULL
		FROM (SELECT action, subject_id, created_at FROM audit_log
		      WHERE action IN ('weekly_fund_request.approve', 'weekly_fund_request.return') AND success
		        AND subject_id = ANY($1)
		      ORDER BY created_at DESC LIMIT $2) g
		LEFT JOIN weekly_fund_request w ON w.id = g.subject_id
		LEFT JOIN "user" u ON u.id = w.responsible_user
		ORDER BY g.created_at DESC`, subjects, recentLimit*3)
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the recent decisions: %w", err)
	}
	today := now.In(zone)
	lines := []string{}
	err = forEach(rows, func(r pgx.Rows) error {
		var action, owner, name string
		var at time.Time
		var weekStart *time.Time
		var known, named bool
		var money int64
		if err := r.Scan(&action, &at, &known, &owner, &weekStart, &money, &name, &named); err != nil {
			return err
		}
		if !known || len(lines) == recentLimit {
			return nil
		}
		if !named {
			name = "Staff"
		}
		verb := "approved"
		if action == "weekly_fund_request.return" {
			verb = "returned for review"
		}
		lines = append(lines, fmt.Sprintf("%s — %s Fund Plan %s %s %s", name, weekStart.Format("Jan"), verb,
			budgetpage.UGXCompact(money), whenLabel(at.In(zone), today)))
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the recent decisions: %w", err)
	}
	return lines, nil
}

// whenLabel is recent_activity's time: "Today, 4:30 PM", "Yesterday, …" or
// "05 Nov, 4:30 PM" (every " 0" read as " ").
func whenLabel(when, now time.Time) string {
	day := func(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }
	var s string
	switch {
	case day(when).Equal(day(now)):
		s = "Today, " + when.Format("03:04 PM")
	case day(when).Equal(day(now).AddDate(0, 0, -1)):
		s = "Yesterday, " + when.Format("03:04 PM")
	default:
		s = when.Format("02 Jan") + ", " + when.Format("03:04 PM")
	}
	return strings.ReplaceAll(s, " 0", " ")
}
