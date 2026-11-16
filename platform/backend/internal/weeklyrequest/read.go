package weeklyrequest

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// args collects a query's arguments.
type args []any

func (a *args) add(v any) string { *a = append(*a, v); return fmt.Sprintf("$%d", len(*a)) }

// requests is the scope's weekly requests of its year (wfr_qs), with the
// district, staff and status filters, as SQL over weekly_fund_request w.
func (sc scope) requests(a ask, q *args) string {
	where := []string{"w.fy = " + q.add(sc.fy)}
	if sc.owners != nil {
		where = append(where, "w.responsible_user = ANY("+q.add(sc.owners)+")")
	}
	if a.district != "" {
		where = append(where, "w.responsible_user IN (SELECT user_id FROM staff_profile WHERE primary_district_id = "+
			q.add(a.district)+" AND deleted_at IS NULL)")
	}
	if sc.staff != "" {
		where = append(where, "w.responsible_user = "+q.add(sc.staff))
	}
	if a.status != "" {
		where = append(where, "w.status = "+q.add(a.status))
	}
	return strings.Join(where, " AND ")
}

// activities is the scope's live activities (activities_qs) over activity a.
func (sc scope) activities(a ask, q *args) string {
	where := []string{"a.deleted_at IS NULL"}
	if sc.actors != nil {
		where = append(where, "a.responsible_staff_id = ANY("+q.add(sc.actors)+")")
	}
	if a.district != "" {
		where = append(where, "a.school_id IN (SELECT id FROM school WHERE district_id = "+q.add(a.district)+")")
	}
	if sc.staff != "" {
		where = append(where, "(a.responsible_staff_id = "+q.add(sc.staff)+
			" OR a.responsible_staff_id IN (SELECT id FROM staff_profile WHERE user_id = "+q.add(sc.staff)+" AND deleted_at IS NULL))")
	}
	return strings.Join(where, " AND ")
}

// lines is the scope's cost lines of its year (budget_qs) over
// activity_schedule_cost_line l.
func (sc scope) lines(a ask, q *args) string {
	where := []string{"l.fiscal_year = " + q.add(sc.fy)}
	if sc.owners != nil {
		where = append(where, "l.responsible_user = ANY("+q.add(sc.owners)+")")
	}
	if a.district != "" {
		where = append(where, "l.school_id IN (SELECT id FROM school WHERE district_id = "+q.add(a.district)+")")
	}
	if sc.staff != "" {
		where = append(where, "l.responsible_user = "+q.add(sc.staff))
	}
	return strings.Join(where, " AND ")
}

// tally is a sum and a count of requests.
type tally struct {
	total int64
	count int
}

func (s *Service) tally(ctx context.Context, sql string, q args) (tally, error) {
	var t tally
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(SUM(w.total_amount), 0)::bigint, count(*) FROM weekly_fund_request w WHERE `+sql, q...).Scan(&t.total, &t.count); err != nil {
		return t, fmt.Errorf("weeklyrequest: summing requests: %w", err)
	}
	return t, nil
}

// monthRequests is the scope's requests of a calendar month, by status set
// (all of them when statuses is nil).
func (s *Service) monthRequests(ctx context.Context, sc scope, a ask, year, month int, statuses []string, extra string) (tally, error) {
	q := args{}
	where := sc.requests(a, &q) + fmt.Sprintf(" AND EXTRACT(YEAR FROM w.week_start_date) = %d AND EXTRACT(MONTH FROM w.week_start_date) = %d", year, month)
	if statuses != nil {
		where += " AND w.status = ANY(" + q.add(statuses) + ")"
	}
	return s.tally(ctx, where+extra, q)
}

// between is the scope's requests whose week starts in [from, to) (or
// [from, to] when inclusive).
func (s *Service) between(ctx context.Context, sc scope, a ask, from, to time.Time, inclusive bool) (tally, error) {
	q := args{}
	op := "<"
	if inclusive {
		op = "<="
	}
	where := sc.requests(a, &q) + " AND w.week_start_date >= " + q.add(from) + " AND w.week_start_date " + op + " " + q.add(to)
	return s.tally(ctx, where, q)
}

// weekRequest is the week's request in view.
type weekRequest struct {
	id, owner, ownerName, status, returnReason, fundingSource string
	total                                                     int64
	receiptConfirmed, submittedAccountability, reviewed       bool
	pendingAccountability                                     bool
}

// errMany is a week shared by more than one request in view: the page shows
// whichever the database returns first, which Go does not guess.
var errMany = errors.New("weeklyrequest: more than one request in the week")

func (s *Service) weekRequest(ctx context.Context, sc scope, a ask, start time.Time) (*weekRequest, error) {
	q := args{}
	rows, err := s.db.Query(ctx, `
SELECT w.id, COALESCE(w.responsible_user, ''), COALESCE(u.name, ''), w.status, COALESCE(w.return_reason, ''),
  COALESCE(w.funding_source, ''), COALESCE(w.total_amount, 0)::bigint, w.receipt_confirmed_at IS NOT NULL,
  w.accountability_submitted_at IS NOT NULL, w.accountability_reviewed_at IS NOT NULL,
  EXISTS (SELECT 1 FROM weekly_fund_request_line s JOIN advance_request r ON r.budget_line_id = s.activity_budget_line_id
          WHERE s.weekly_fund_request_id = w.id AND r.status = 'accountability_pending'),
  EXISTS (SELECT 1 FROM staff_profile sp WHERE sp.user_id = w.responsible_user AND sp.deleted_at IS NULL)
FROM weekly_fund_request w LEFT JOIN "user" u ON u.id = w.responsible_user
WHERE `+sc.requests(a, &q)+` AND w.week_start_date = `+q.add(start)+` LIMIT 2`, q...)
	if err != nil {
		return nil, fmt.Errorf("weeklyrequest: reading the week's request: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (weekRequest, error) {
		var w weekRequest
		var profile bool
		err := row.Scan(&w.id, &w.owner, &w.ownerName, &w.status, &w.returnReason, &w.fundingSource, &w.total,
			&w.receiptConfirmed, &w.submittedAccountability, &w.reviewed, &w.pendingAccountability, &profile)
		if !profile || w.ownerName == "" {
			w.ownerName = w.owner
		}
		return w, err
	})
	if err != nil {
		return nil, fmt.Errorf("weeklyrequest: reading the week's request: %w", err)
	}
	switch len(list) {
	case 0:
		return nil, nil
	case 1:
		return &list[0], nil
	}
	return nil, errMany
}

// selfHealWrites is whether the existing page would write the reader's own
// missing request for the week as it opens (_self_heal_weekly_request).
func (s *Service) selfHealWrites(ctx context.Context, userID, staffID string, sc scope, a ask, start time.Time) (bool, error) {
	if staffID == "" {
		return false, nil
	}
	var has bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM weekly_fund_request WHERE responsible_user = $1 AND week_start_date = $2)`,
		userID, start).Scan(&has); err != nil {
		return false, fmt.Errorf("weeklyrequest: reading the reader's request: %w", err)
	}
	if has {
		return false, nil
	}
	q := args{}
	where := sc.activities(a, &q)
	err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity a WHERE `+where+
		` AND a.responsible_staff_id = `+q.add(staffID)+
		` AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date BETWEEN `+q.add(start)+` AND `+q.add(start.AddDate(0, 0, 6))+
		` AND a.status <> 'cancelled')`, q...).Scan(&has)
	if err != nil {
		return false, fmt.Errorf("weeklyrequest: reading the reader's week: %w", err)
	}
	return has, nil
}
