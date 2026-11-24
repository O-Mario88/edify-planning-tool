package activities

// Work completed on another day than planned moves to that day with its
// money (apps.activities.completed_day.move_to_completed_day, owner,
// 2026-10-16), with the existing application absent: after the hand-in, the
// work takes the day it was done (its time of day kept), the planned day is
// kept as planned_date_before_completion, and the money moves as a
// reschedule moves it (_reprice_moved_activity: the day left and the day
// joined, the weeks re-filed, a sent week taken back). Done in another
// financial year, it stays where it was planned and the reason is recorded.
// Whether the move is Go's case is decided before the completion is made, so
// a move Go cannot make hands the whole completion on.

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	movedToDoneDayAction  = "activity_moved_to_completed_day"
	keptOnPlannedAction   = "activity_completed_on_another_day"
	otherFinancialYear    = "the day it was done is in another financial year"
	completedOnReasonForm = "02 Jan 2006"
)

// doneDay is the move a completion makes after its hand-in, decided before.
type doneDay struct {
	move       *movePlan // nil when the work stays on its planned day
	row        int64     // the costs-to-follow row the move wrote, priced last
	kept       string    // why it stays, when it does
	planned    time.Time // the day it was planned for
	lastReason string    // the trail row's reason (schedule_trail keeps last_reason)
}

// doneDayWork reads the work a completion moves: dated, on a day, staff's,
// with no project, partner, pair or end date; its status and start do not
// matter, as completion starts it.
func doneDayWork(ctx context.Context, q Querier, id string, session bool) (*moved, string, string, string, error) {
	var a moved
	var school, responsible, batch, itemID, name, clusterID, lastReason, fy *string
	var planned, scheduled *time.Time
	var other bool
	err := q.QueryRow(ctx, `
SELECT a.id, a.activity_type, a.status, a.school_id, a.responsible_staff_id, a.daily_visit_batch_id,
       a.catalogue_item_id, a.activity_name_snapshot, a.scheduled_date, a.planned_date, a.reschedule_count,
       a.cluster_id, a.last_reason, a.fy,
       (a.project_id IS NOT NULL OR a.assigned_partner_id IS NOT NULL OR a.delivery_type IS DISTINCT FROM 'staff'
        OR a.paired_school_visit_id IS NOT NULL OR a.end_date IS NOT NULL
        OR EXISTS (SELECT 1 FROM activity o WHERE o.paired_school_visit_id = a.id))
FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&a.id, &a.activityType, &a.status, &school, &responsible, &batch, &itemID, &name,
		&scheduled, &planned, &a.count, &clusterID, &lastReason, &fy, &other)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, "", "", "", nil
	}
	if err != nil {
		return nil, "", "", "", fmt.Errorf("activities: reading the work to move: %w", err)
	}
	if other || planned == nil || scheduled == nil || (session && clusterID == nil) || (!session && school == nil) {
		return nil, "", "", "", nil
	}
	a.schoolID, a.responsible = text(school), text(responsible)
	a.batchID, a.itemID, a.nameSnapshot = text(batch), text(itemID), text(name)
	a.plannedDate, a.scheduled = *planned, *scheduled
	return &a, text(clusterID), text(lastReason), text(fy), nil
}

// prepareDoneDay decides the move for work done on delivered, or hands the
// completion on.
func (s *Service) prepareDoneDay(ctx context.Context, pl *completionPlan, session bool) (*doneDay, error) {
	a, clusterID, lastReason, fy, err := doneDayWork(ctx, s.db, pl.a.id, session)
	if err != nil {
		return nil, err
	}
	if a == nil || a.batchID == "" || (!session && a.nameSnapshot == "") {
		return nil, handOn("done on another day: work not on a day of its own")
	}
	done := &doneDay{planned: a.plannedDate, lastReason: lastReason}
	if schooldirectory.OperationalFY(pl.delivered) != fy {
		done.kept = otherFinancialYear
		return done, nil
	}
	ownerUID, err := fundingOwner(ctx, s.db, a.responsible, pl.p.UserID)
	if err != nil {
		return nil, err
	}
	reason := completedOnReason(pl.delivered)
	posted := pl.delivered.Format(time.DateOnly)
	mover, ok := s.pricing.(MovePricing)
	if !ok {
		return nil, fmt.Errorf("activities: the pricing cannot check a move")
	}
	verdict, err := mover.MoveCheck(ctx, a.id, posted, reason)
	if err != nil {
		return nil, err
	}
	if verdict.Refusal != "" || verdict.LeftFrozen || !verdict.Pooled || (session && verdict.TakesBack) {
		return nil, handOn("done on another day: the move's money or day refuses it")
	}
	weeks, months, err := lineBuckets(ctx, s.db, a.id)
	if err != nil {
		return nil, err
	}
	if len(weeks) > 1 || len(months) > 1 {
		return nil, handOn("done on another day: the lines sit in more than one week or month")
	}
	var it *item
	if a.itemID != "" {
		if it, err = itemByID(ctx, s.db, a.itemID); err != nil {
			return nil, err
		}
	}
	home, err := staffHomeOf(ctx, s.db, a.responsible)
	if err != nil {
		return nil, err
	}
	where, clusterName, err := s.doneDayPlace(ctx, a, session, clusterID)
	if err != nil {
		return nil, err
	}
	day := pl.delivered
	scheduled := onDoneDay(a.scheduled, day, s.kampala)
	done.move = &movePlan{
		p: pl.p, a: *a, school: where, item: it, home: home, ownerUID: ownerUID, reason: reason, posted: posted,
		scheduled: scheduled, newDay: day, fy: fy, quarter: quarterOf(day),
		month: int(day.Month()), week: min(5, (day.Day()-1)/7+1),
		weeks: weeks, months: months, verdict: verdict, origin: pl.origin, now: pl.now,
		session: session, clusterName: clusterName, unnoted: true,
	}
	return done, nil
}

// doneDayPlace is where the work's day is made: its school, or its cluster.
func (s *Service) doneDayPlace(ctx context.Context, a *moved, session bool, clusterID string) (school, string, error) {
	if !session {
		sc, err := schoolByIDOrCode(ctx, s.db, a.schoolID)
		if err != nil {
			return school{}, "", err
		}
		if sc == nil || sc.ID != a.schoolID {
			return school{}, "", handOn("done on another day: no school")
		}
		return *sc, "", nil
	}
	cl, err := clusterOf(ctx, s.db, clusterID)
	if err != nil {
		return school{}, "", err
	}
	if cl == nil {
		return school{}, "", handOn("done on another day: no live cluster")
	}
	var name string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM cluster WHERE id = $1`, clusterID).Scan(&name); err != nil {
		return school{}, "", fmt.Errorf("activities: reading the cluster's name: %w", err)
	}
	return school{Name: name, DistrictID: cl.DistrictID, DistrictName: cl.DistrictName, DistrictType: cl.DistrictType}, name, nil
}

// moveToDoneDay is _move after the hand-in has committed: the weeks taken
// back, the day joined, the work's day, the trail row and the costs to
// follow in one transaction, then the move's audit row. The pricing follows
// the completion's own rows (settleDoneDay), as the existing move's costs
// follow on commit. A failure here leaves the completion made and the money
// on its planned day for the sweep, as the existing move never refuses the
// completion.
func (s *Service) moveToDoneDay(ctx context.Context, done *doneDay) {
	pl := done.move
	rowID, err := s.writeDoneDay(ctx, done)
	if err != nil {
		s.logger.Warn("activities: the completed work was not moved to its day", "activity", pl.a.id, "err", err)
		return
	}
	done.row = rowID
	if err := s.auditDoneDay(ctx, pl.p.UserID, pl.p.ActiveRole, pl.a.id, pl.origin, done.planned, pl.newDay, ""); err != nil {
		s.logger.Warn("activities: the move's audit row was not written", "activity", pl.a.id, "err", err)
	}
}

// settleDoneDay prices the moved work once the completion's rows are
// written, and tells the owners of a week taken back.
func (s *Service) settleDoneDay(ctx context.Context, done *doneDay) {
	if done == nil || done.move == nil || done.row == 0 {
		return
	}
	pl := done.move
	if err := s.pricing.Settle(ctx, []int64{done.row}, pl.a.id); err != nil {
		s.logger.Warn("activities: the costs to follow were not settled; the sweep takes them",
			"activity", pl.a.id, "row", done.row, "err", err)
	}
	if len(pl.taken) > 0 {
		s.tellTakenBack(ctx, pl)
	}
}

func (s *Service) writeDoneDay(ctx context.Context, done *doneDay) (int64, error) {
	pl := done.move
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("activities: opening the move to the day done: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if pl.verdict.TakesBack {
		if err := takeBackWeeks(ctx, tx, pl); err != nil {
			return 0, err
		}
	}
	var status string
	if err := tx.QueryRow(ctx, `SELECT status FROM activity WHERE id = $1 FOR UPDATE`, pl.a.id).Scan(&status); err != nil {
		return 0, fmt.Errorf("activities: locking the work: %w", err)
	}
	newBatch, err := s.joinMovedDay(ctx, tx, pl)
	if err != nil {
		return 0, err
	}
	pl.newBatch = newBatch
	if _, err := tx.Exec(ctx, `UPDATE activity SET scheduled_date = $2, quarter = $3, planned_date = $4,
  planned_month = $5, planned_week = $6, daily_visit_batch_id = $7,
  planned_date_before_completion = COALESCE(planned_date_before_completion, $8), updated_at = $9 WHERE id = $1`,
		pl.a.id, pl.scheduled, pl.quarter, pl.newDay.Format(time.DateOnly), pl.month, pl.week, newBatch,
		done.planned.Format(time.DateOnly), pl.now); err != nil {
		return 0, fmt.Errorf("activities: moving the work to the day done: %w", err)
	}
	if _, err := tx.Exec(ctx, `INSERT INTO activity_schedule_change (id, kind, from_day, to_day, from_status,
  to_status, reason, changed_at, activity_id) VALUES ($1, 'rescheduled', $2, $3, $4, $4, $5, $6, $7)`,
		cuid.New(), done.planned.Format(time.DateOnly), pl.newDay.Format(time.DateOnly), status,
		truncateRunes(done.lastReason, 512), pl.now, pl.a.id); err != nil {
		return 0, fmt.Errorf("activities: writing the schedule trail: %w", err)
	}
	rowID, err := keepMoveCosts(ctx, tx, pl)
	if err != nil {
		return 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("activities: committing the move to the day done: %w", err)
	}
	return rowID, nil
}

// auditDoneDay is completed_day._audit: moved, or kept with its reason.
func (s *Service) auditDoneDay(ctx context.Context, actor, role, id string, origin Origin, planned, day time.Time, kept string) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, actor, s.now())
	if err != nil {
		return err
	}
	action := movedToDoneDayAction
	if kept != "" {
		action = keptOnPlannedAction
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(id),
		ActorID: audit.Text(actor), ActorRole: &role, Success: true, Reason: audit.Text(kept),
		Payload: withStamps(map[string]any{
			"plannedDate": planned.Format(time.DateOnly), "completedOn": day.Format(time.DateOnly), "moved": kept == "",
		}, cover),
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent),
		CorrelationID: nilIfEmpty(origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// afterDoneDay is move_to_completed_day after the hand-in: the move, or the
// reason the work stays.
func (s *Service) afterDoneDay(ctx context.Context, pl *completionPlan) {
	done := pl.done
	if done == nil {
		return
	}
	if done.move == nil {
		if err := s.auditDoneDay(ctx, pl.p.UserID, pl.p.ActiveRole, pl.a.id, pl.origin, done.planned, pl.delivered, done.kept); err != nil {
			s.logger.Warn("activities: the kept day's audit row was not written", "activity", pl.a.id, "err", err)
		}
		return
	}
	s.moveToDoneDay(ctx, done)
}

// completedOnReason is the reason the move is priced with ("Completed on
// %d %b %Y").
func completedOnReason(day time.Time) string {
	return "Completed on " + day.Format(completedOnReasonForm)
}

// onDoneDay is the work's new moment: the day it was done, at the local time
// of day it was scheduled for.
func onDoneDay(scheduled, day time.Time, loc *time.Location) time.Time {
	local := scheduled.In(loc)
	return time.Date(day.Year(), day.Month(), day.Day(), local.Hour(), local.Minute(), local.Second(),
		local.Nanosecond(), loc)
}
