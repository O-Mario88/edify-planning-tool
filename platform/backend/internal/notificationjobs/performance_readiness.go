package notificationjobs

// _do_performance_readiness (apps.hr.performance_engine.quarterly_readiness):
// seven days before a quarter ends, Human Resources is told how many staff
// are in the cycle, how many have no agreed priorities and how many no
// manager. Any other day it tells nobody. The existing job counts one run.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// quarterOf is get_quarter_for_date and the quarter's last month and day.
func quarterOf(m time.Month) (string, time.Month, int) {
	switch {
	case m >= time.October:
		return "Q1", time.December, 31
	case m <= time.March:
		return "Q2", time.March, 31
	case m <= time.June:
		return "Q3", time.June, 30
	}
	return "Q4", time.September, 30
}

// daysToQuarterEnd is the quarter today falls in and the days to its end.
func daysToQuarterEnd(today time.Time) (string, int) {
	q, m, d := quarterOf(today.Month())
	end := time.Date(today.Year(), m, d, 0, 0, 0, 0, time.UTC)
	if end.Before(today) {
		end = end.AddDate(1, 0, 0)
	}
	return q, int(end.Sub(today).Hours() / 24)
}

// PerformanceReadiness is the job for today in Kampala.
func PerformanceReadiness(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, n Notices) (int, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	q, days := daysToQuarterEnd(today)
	if days != 7 {
		return 1, nil
	}
	fy := schooldirectory.OperationalFY(local)
	var inCycle, missingPriorities, missingManagers int
	if err := tx.QueryRow(ctx, `
WITH staff AS (SELECT id FROM staff_profile WHERE deleted_at IS NULL AND onboarding_state = 'active')
SELECT (SELECT count(*)::int FROM staff),
  (SELECT count(*)::int FROM staff WHERE id NOT IN (SELECT staff_id FROM hr_performance_review
     WHERE fy = $1 AND review_type = 'annual_priorities' AND staff_id IS NOT NULL)),
  (SELECT count(*)::int FROM staff WHERE id NOT IN (SELECT a.supervisee_id FROM staff_supervisor_assignment a
     JOIN staff_profile sp ON sp.id = a.supervisee_id WHERE sp.deleted_at IS NULL))`, fy).
		Scan(&inCycle, &missingPriorities, &missingManagers); err != nil {
		// The existing check never lets the notice stop the run.
		logNotice(ctx, n.Logger, err)
		return 1, nil
	}
	hr, err := holders(ctx, tx, "HumanResources")
	if err != nil {
		logNotice(ctx, n.Logger, err)
		return 1, nil
	}
	to := make([]activities.NoticeTo, 0, len(hr))
	for _, h := range hr {
		to = append(to, activities.NoticeTo{UserID: h.userID, Route: "/dashboard", Label: "View Dashboard"})
	}
	if _, err := activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, fy, activities.Notice{
		Title: q + " performance conversations open in 7 days",
		Body: fmt.Sprintf("%d staff in cycle · %d without approved priorities · %d without a manager. "+
			"Review readiness and activate the window.", inCycle, missingPriorities, missingManagers),
		Event: "performance_window_due", Category: "hr", ContextType: "PerformanceCycle", Priority: "high",
	}, to); err != nil {
		logNotice(ctx, n.Logger, err)
	}
	return 1, nil
}

func logNotice(ctx context.Context, logger *slog.Logger, err error) {
	if logger != nil {
		logger.WarnContext(ctx, "notificationjobs: the readiness notice was not sent", "err", err)
	}
}
