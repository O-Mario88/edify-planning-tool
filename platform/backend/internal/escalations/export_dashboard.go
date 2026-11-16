package escalations

import (
	"context"
	"fmt"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Dashboard is what a Programme Lead's dashboard reads of escalations
// (pl_dashboard_service.waiting_on_you and collaboration_items).
type Dashboard struct {
	// ToDecide are those addressed to the reader, not resolved and not their
	// own; Overdue how many of them are past their severity's SLA.
	ToDecide, Overdue int
	// RaisedOpen is the reader's own not yet resolved (the first limit), and
	// DelegatedBack theirs decided "delegated back" within the days (the
	// first limit/2).
	RaisedOpen, RaisedOverdue, DelegatedBack int
}

// overdue is _is_overdue: open and at least its SLA's days old.
func overdue(status, severity string, created, now time.Time) bool {
	return status == rules.Statuses.Open && int(now.Sub(created).Hours()/24) >= slaDays(severity)
}

// ForDashboard reads the reader's escalations as the dashboard counts them.
func ForDashboard(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time,
	raisedLimit, delegatedLimit, delegatedDays int) (Dashboard, error) {
	var out Dashboard
	args := []any{}
	inbox, err := InboxClause(ctx, db, p, &args)
	if err != nil {
		return out, err
	}
	count := func(sql string, args []any, each func(status, severity string, created time.Time)) error {
		rows, err := db.Query(ctx, sql, args...)
		if err != nil {
			return fmt.Errorf("escalations: dashboard: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var status, severity string
			var created time.Time
			if err := rows.Scan(&status, &severity, &created); err != nil {
				return fmt.Errorf("escalations: dashboard: %w", err)
			}
			each(status, severity, created)
		}
		return rows.Err()
	}
	if inbox != "" {
		args = append(args, p.UserID, rules.Statuses.Resolved)
		sql := fmt.Sprintf(`SELECT COALESCE(status, ''), COALESCE(severity, ''), created_at FROM leadership_escalation
WHERE %s AND status IS DISTINCT FROM $%d AND raised_by_user_id IS DISTINCT FROM $%d`, inbox, len(args), len(args)-1)
		if err := count(sql, args, func(status, severity string, created time.Time) {
			out.ToDecide++
			if overdue(status, severity, created, now) {
				out.Overdue++
			}
		}); err != nil {
			return out, err
		}
	}
	if err := count(`SELECT COALESCE(status, ''), COALESCE(severity, ''), created_at FROM leadership_escalation
WHERE raised_by_user_id = $1 AND status IS DISTINCT FROM $2 ORDER BY created_at ASC LIMIT $3`,
		[]any{p.UserID, rules.Statuses.Resolved, raisedLimit}, func(status, severity string, created time.Time) {
			out.RaisedOpen++
			if overdue(status, severity, created, now) {
				out.RaisedOverdue++
			}
		}); err != nil {
		return out, err
	}
	err = db.QueryRow(ctx, `SELECT count(*) FROM (SELECT 1 FROM leadership_escalation
WHERE raised_by_user_id = $1 AND status = $2 AND decision = 'delegated_back' AND resolved_at >= $3 LIMIT $4) d`,
		p.UserID, rules.Statuses.Resolved, now.Add(-time.Duration(delegatedDays)*24*time.Hour), delegatedLimit).Scan(&out.DelegatedBack)
	if err != nil {
		return out, fmt.Errorf("escalations: dashboard: %w", err)
	}
	return out, nil
}
