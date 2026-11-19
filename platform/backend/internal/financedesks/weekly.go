package financedesks

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
)

// The Weekly Staff Fund Requests registry (weekly_requests_view): every
// weekly request, latest week first, with its owner, its lines and its
// money as stored.

func (s *Service) weeklyRequests(ctx context.Context, _ role, query url.Values) (*screensv1.GetPageResponse, error) {
	// The view's own ordering, with nothing to break a tie: requests of the
	// same week come back in the order the database gives them, as they do
	// to the existing page.
	rows, err := s.db.Query(ctx, `
SELECT r.id, r.week_start_date, r.week_end_date, COALESCE(r.responsible_user, ''), r.total_amount, r.disbursed_amount,
  COALESCE(r.status, ''), u.id IS NOT NULL, u.name,
  (SELECT COUNT(*) FROM weekly_fund_request_line l WHERE l.weekly_fund_request_id = r.id)
FROM weekly_fund_request r LEFT JOIN "user" u ON u.id = r.responsible_user
ORDER BY r.week_start_date DESC`)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the weekly requests: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageRow, error) {
		var id, owner, status string
		var start, end *time.Time
		var total, disbursed *int64
		var known bool
		var name *string
		var lines int
		if err := row.Scan(&id, &start, &end, &owner, &total, &disbursed, &status, &known, &name, &lines); err != nil {
			return nil, err
		}
		who := owner
		if known {
			who = pyStr(name)
		}
		paid := "0"
		if disbursed != nil && *disbursed != 0 {
			paid = strconv.FormatInt(*disbursed, 10)
		}
		requested := "None"
		if total != nil {
			requested = strconv.FormatInt(*total, 10)
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(joined(isoWeek(start), day(start)+" to "+day(end))), cell(who), cell(strconv.Itoa(lines)),
			cell(requested + " UGX"), cell(paid + " UGX"), badge(stafflogs.StatusLabel(status)),
			button("Clear Advances", "/accounts/advances/"),
		}}, nil
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the weekly requests: %w", err)
	}
	return page(header("Finance", "Weekly Staff Fund Requests",
		"Monitor weekly requests submitted by CCEOs for scheduled field activities."),
		table(columns([]string{"Week / Period", "Staff Member", "Activities Count", "Requested Amount", "Disbursed Amount",
			"Status", "Actions"}, "Actions"), list, "No active weekly requests generated.", "requests_page", query)...), nil
}

// isoWeek is date:"Y-\WW": the calendar year, then the ISO week number.
func isoWeek(d *time.Time) string {
	if d == nil {
		return ""
	}
	_, week := d.ISOWeek()
	return strconv.Itoa(d.Year()) + "-W" + strconv.Itoa(week)
}

// day is date:"Y-m-d".
func day(d *time.Time) string {
	if d == nil {
		return ""
	}
	return d.Format(time.DateOnly)
}
