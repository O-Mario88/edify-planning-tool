package activities

// Activity.save's Core package mirror for live work outside a cluster: each
// package slot the work fills takes the work's status (core_slot_status), its
// day, its Salesforce ID and, when the slot has none, the work's newest
// evidence file, and the package's done counters are recomputed. Work called
// off, a cluster session, and Core School work holding no slot (which the
// package credit would link after commit) are the caller's to hand on.

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// ErrSlotMirrorHandedOn is work whose save does more to the package than
// the mirror: a cluster session's credit, a called-off visit's give-back, or
// the package credit of Core School work holding no slot.
var ErrSlotMirrorHandedOn = errors.New("activities: the package side of this save is handed on")

// notInPlanStatuses are NOT_IN_PLAN_ACTIVITY_STATUSES.
var notInPlanStatuses = []string{"cancelled", "rejected", "deferred", "not_planned"}

// SlotMirrorHandedOn says, before a save, whether its package side is one
// the mirror does not do (ErrSlotMirrorHandedOn's cases) for the work as it
// will stand with status.
func SlotMirrorHandedOn(ctx context.Context, q Querier, activityID, status string) (bool, error) {
	var cluster, coreSchool, holdsSlot bool
	err := q.QueryRow(ctx, `SELECT a.cluster_id IS NOT NULL, COALESCE(s.school_type = 'core', false),
  EXISTS (SELECT 1 FROM core_activity_slot c WHERE c.activity_id = a.id)
FROM activity a LEFT JOIN school s ON s.id = a.school_id WHERE a.id = $1`, activityID).Scan(&cluster, &coreSchool, &holdsSlot)
	if err != nil {
		return false, fmt.Errorf("activities: reading the work's package side: %w", err)
	}
	return cluster || in(notInPlanStatuses, status) || (coreSchool && !holdsSlot), nil
}

// MirrorSlots is the mirror, inside the caller's transaction, after the
// activity row is written.
func MirrorSlots(ctx context.Context, tx pgx.Tx, activityID string, kampala *time.Location, now time.Time) error {
	var status, salesforce string
	var scheduled *time.Time
	if err := tx.QueryRow(ctx, `SELECT COALESCE(status, ''), COALESCE(salesforce_activity_id, ''), scheduled_date
FROM activity WHERE id = $1`, activityID).Scan(&status, &salesforce, &scheduled); err != nil {
		return fmt.Errorf("activities: reading the work for its package slots: %w", err)
	}
	var day *string
	if scheduled != nil {
		d := scheduled.In(kampala).Format(time.DateOnly)
		day = &d
	}
	rows, err := tx.Query(ctx, `UPDATE core_activity_slot c SET status = $2,
  scheduled_for = COALESCE($3::varchar, c.scheduled_for),
  salesforce_id = CASE WHEN $4 <> '' THEN $4 ELSE c.salesforce_id END,
  evidence_uri = CASE WHEN COALESCE(c.evidence_uri, '') = '' THEN (SELECT e.uri FROM evidence_record e
      WHERE e.activity_id = $1 AND NOT e.quarantined ORDER BY e.created_at DESC LIMIT 1) ELSE c.evidence_uri END,
  updated_at = $5
WHERE c.activity_id = $1 RETURNING c.core_plan_id`, activityID, coreSlotStatus(status), day, salesforce, now)
	if err != nil {
		return fmt.Errorf("activities: mirroring the work to its package slots: %w", err)
	}
	plans, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return fmt.Errorf("activities: mirroring the work to its package slots: %w", err)
	}
	for _, plan := range plans {
		if err := resyncPlanCompletion(ctx, tx, plan, now); err != nil {
			return err
		}
	}
	return nil
}

// resyncPlanCompletion is resync_plan_completion: the package's done
// counters recomputed from its slots, written when they moved.
func resyncPlanCompletion(ctx context.Context, tx pgx.Tx, planID string, now time.Time) error {
	if _, err := tx.Exec(ctx, `UPDATE core_plan p SET visits_completed = c.visits, trainings_completed = c.trainings, updated_at = $3
FROM (SELECT count(*) FILTER (WHERE activity_type = 'visit' AND status = ANY($2)) AS visits,
             count(*) FILTER (WHERE activity_type = 'training' AND status = ANY($2)) AS trainings
      FROM core_activity_slot WHERE core_plan_id = $1) c
WHERE p.id = $1 AND (p.visits_completed IS DISTINCT FROM c.visits OR p.trainings_completed IS DISTINCT FROM c.trainings)`,
		planID, coreDoneStatuses, now); err != nil {
		return fmt.Errorf("activities: recounting the package: %w", err)
	}
	return nil
}
