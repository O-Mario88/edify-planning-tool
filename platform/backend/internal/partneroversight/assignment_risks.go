package partneroversight

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// AssignmentRiskKeys is build_item_by_assignment with
// partner_risk_service.annotate, as the delegated-action sweep asks it: the
// keys of the risks one hand-over carries today. Unscoped, as the existing
// builder is; found is false when the hand-over is gone.
func AssignmentRiskKeys(ctx context.Context, db schooldirectory.Querier, id string, today time.Time) ([]string, bool, error) {
	it := &item{}
	var activityID string
	var created time.Time
	err := db.QueryRow(ctx, `SELECT status, COALESCE(scheduled_activity_id, ''), created_at FROM partner_assignment WHERE id = $1`, id).
		Scan(&it.assignmentStatus, &activityID, &created)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("partneroversight: the hand-over: %w", err)
	}
	var a *activity
	if activityID != "" {
		acts, err := readActivities(ctx, db, `a.id = ANY($1)`, []string{activityID})
		if err != nil {
			return nil, false, err
		}
		if len(acts) > 0 {
			a = acts[0]
		}
	}
	// _item_for's stage: a hand-back, scheduled work, else awaiting a date.
	switch {
	case it.assignmentStatus == rules.ReturnedToStaff:
		it.stage = stageReturned
	case a != nil:
		it.stage = stageScheduled
	default:
		it.stage = stageAwaiting
	}
	day := dateOf(created.In(zone))
	it.assignmentDate = &day
	if a != nil {
		costs, err := readCosts(ctx, db, []string{a.id})
		if err != nil {
			return nil, false, err
		}
		fill(it, a, costs)
	}
	return risksOf(it, today), true, nil
}
