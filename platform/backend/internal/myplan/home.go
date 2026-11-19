package myplan

import (
	"context"
	"fmt"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// HomeCounts is Home's plan figures (apps.command_center.home_service.
// plan_figures): how much of the reader's own plan is not started with its
// day ahead, under way, and not started with its day passed. Each is the
// My Plan status filter the figure opens (plan_state_q), so the figure and
// the list cannot disagree.
type HomeCounts struct {
	Upcoming, UnderWay, Overdue int
}

// ReadHomeCounts counts plan in the year fy on the day today.
func ReadHomeCounts(ctx context.Context, db schooldirectory.Querier, plan PlanOf, fy string, today time.Time) (HomeCounts, error) {
	day := today.In(kampala).Format(time.DateOnly)
	var out HomeCounts
	for _, state := range []struct {
		name string
		into *int
	}{{"upcoming", &out.Upcoming}, {"under_way", &out.UnderWay}, {"overdue", &out.Overdue}} {
		b := &sqlb{}
		where := planWhereOf(b, plan, fy, Filters{Status: state.name}, day)
		if err := db.QueryRow(ctx, `SELECT count(*) `+planFrom+` WHERE `+where, b.args...).Scan(state.into); err != nil {
			return out, fmt.Errorf("myplan: counting the plan's %s work: %w", state.name, err)
		}
	}
	return out, nil
}

// HomeActivity is one of Home's upcoming activities, as read.
type HomeActivity struct {
	ID, Purpose, Type, Status string
	SchoolID, SchoolName      string
	ClusterID, ClusterName    string
	Planned                   *time.Time
	Scheduled                 *time.Time
}

// ReadHomeUpcoming is home_service.upcoming_activities: the reader's next
// not-started activities that carry a date, soonest first.
func ReadHomeUpcoming(ctx context.Context, db schooldirectory.Querier, plan PlanOf, fy string, today time.Time, limit int) ([]HomeActivity, error) {
	b := &sqlb{}
	where := planWhereOf(b, plan, fy, Filters{Status: "upcoming"}, today.In(kampala).Format(time.DateOnly))
	rows, err := db.Query(ctx, `SELECT a.id, COALESCE(a.activity_purpose_text, ''), COALESCE(a.activity_type, ''), COALESCE(a.status, ''),
  COALESCE(a.school_id, ''), COALESCE(s.name, ''), COALESCE(a.cluster_id, ''), COALESCE(c.name, ''), a.planned_date, a.scheduled_date
`+planFrom+` WHERE `+where+` AND (a.planned_date IS NOT NULL OR a.scheduled_date IS NOT NULL)
ORDER BY a.planned_date, a.scheduled_date, a.id LIMIT `+b.arg(limit), b.args...)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the upcoming plan: %w", err)
	}
	defer rows.Close()
	out := []HomeActivity{}
	for rows.Next() {
		var a HomeActivity
		if err := rows.Scan(&a.ID, &a.Purpose, &a.Type, &a.Status, &a.SchoolID, &a.SchoolName, &a.ClusterID, &a.ClusterName, &a.Planned, &a.Scheduled); err != nil {
			return nil, fmt.Errorf("myplan: reading an upcoming activity: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}
