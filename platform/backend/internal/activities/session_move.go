package activities

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Moving a cluster meeting to another day (services.reschedule for work at
// a cluster, no school): the same save as a visit's, its day made where its
// cluster is. A training (its schools' places under a ceiling), a partner's
// work and anything not on a day of its own are handed on.

// changeName is plan_changes._named: the work, and where it is.
func (pl *movePlan) changeName() string {
	if !pl.session {
		return pl.a.nameSnapshot + " at " + pl.school.Name
	}
	what := pl.a.nameSnapshot
	if what == "" {
		what = myplan.TypeLabel(pl.a.activityType)
	}
	return what + " for " + pl.clusterName
}

// movedSession reads a staff cluster meeting a move takes: dated, on a day,
// with no school, project, partner, pair, end date or start.
func movedSession(ctx context.Context, q Querier, id string) (*moved, string, string, error) {
	if id == "" {
		return nil, "", "", nil
	}
	var a moved
	var responsible, batch, itemID, name, meetingKind, clusterID *string
	var planned, scheduled *time.Time
	var other bool
	err := q.QueryRow(ctx, `
SELECT a.id, a.activity_type, a.status, a.responsible_staff_id, a.daily_visit_batch_id, a.catalogue_item_id,
       a.activity_name_snapshot, a.scheduled_date, a.planned_date, a.reschedule_count, a.meeting_kind, a.cluster_id,
       (a.school_id IS NOT NULL OR a.project_id IS NOT NULL OR a.assigned_partner_id IS NOT NULL
        OR a.delivery_type IS DISTINCT FROM 'staff' OR a.paired_school_visit_id IS NOT NULL
        OR a.end_date IS NOT NULL OR a.execution_started_at IS NOT NULL
        OR EXISTS (SELECT 1 FROM activity o WHERE o.paired_school_visit_id = a.id))
FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&a.id, &a.activityType, &a.status, &responsible, &batch, &itemID, &name,
		&scheduled, &planned, &a.count, &meetingKind, &clusterID, &other)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && (other || clusterID == nil || planned == nil || scheduled == nil)) {
		return nil, "", "", nil
	}
	if err != nil {
		return nil, "", "", fmt.Errorf("activities: reading the session: %w", err)
	}
	a.responsible, a.batchID, a.itemID, a.nameSnapshot = text(responsible), text(batch), text(itemID), text(name)
	a.plannedDate, a.scheduled = *planned, *scheduled
	return &a, text(clusterID), text(meetingKind), nil
}

// prepareSessionMove is prepareMove for a cluster meeting.
func (s *Service) prepareSessionMove(ctx context.Context, p auth.Principal, req MoveRequest, origin Origin, now, today time.Time) (*movePlan, error) {
	a, clusterID, meetingKind, err := movedSession(ctx, s.db, strings.TrimSpace(req.ActivityID))
	if err != nil {
		return nil, err
	}
	if a == nil || !ownsVisit(p, a.responsible) || !in(movableStatuses, a.status) || a.batchID == "" ||
		!myplan.IsClusterMeeting(a.activityType) || myplan.IsTraining(a.activityType, meetingKind) {
		return nil, handOn("not a scheduled visit of the first save's kind, owned by the person")
	}
	access, err := myplan.ReadActivityAccess(ctx, s.db, p, a.id, now)
	if err != nil {
		return nil, err
	}
	if !access.Decided || !access.Runnable {
		return nil, handOn("a session the person may not run")
	}
	cl, err := clusterOf(ctx, s.db, clusterID)
	if err != nil {
		return nil, err
	}
	if cl == nil {
		return nil, handOn("a session at no live cluster")
	}
	var clusterName string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM cluster WHERE id = $1`, clusterID).Scan(&clusterName); err != nil {
		return nil, fmt.Errorf("activities: reading the cluster's name: %w", err)
	}
	ownerUID, err := fundingOwner(ctx, s.db, a.responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	if handOnWhy, err := moveNotices(ctx, s.db, a.id, ownerUID); err != nil || handOnWhy != "" {
		if err != nil {
			return nil, err
		}
		return nil, handOn(handOnWhy)
	}
	// The view's fields and _parse_date, then assert_date_plannable.
	posted := strings.TrimSpace(req.Date)
	reason := strings.TrimSpace(req.Reason)
	if posted == "" {
		return nil, refuse("Invalid date: ")
	}
	if !isoDate.MatchString(posted) {
		return nil, handOn("a date in another form")
	}
	newDay, err := time.ParseInLocation(time.DateOnly, posted, s.kampala)
	if err != nil {
		return nil, refuse("Invalid date: %s", posted)
	}
	if newDay.Before(today) {
		return nil, refuse("%s has passed. Schedule work from %s onwards.", longDate(newDay), longDate(today))
	}
	mover, ok := s.pricing.(MovePricing)
	if !ok {
		return nil, fmt.Errorf("activities: the pricing cannot check a move")
	}
	verdict, err := mover.MoveCheck(ctx, a.id, posted, reason)
	if err != nil {
		return nil, err
	}
	if verdict.LeftFrozen || !verdict.Pooled {
		return nil, handOn("the move's money has moved, or its day is not pooled")
	}
	weeks, months, err := lineBuckets(ctx, s.db, a.id)
	if err != nil {
		return nil, err
	}
	if len(weeks) > 1 || len(months) > 1 {
		return nil, handOn("the session's lines sit in more than one week or month")
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
	scheduledUTC := newDay.UTC()
	where := school{Name: clusterName, DistrictID: cl.DistrictID, DistrictName: cl.DistrictName, DistrictType: cl.DistrictType}
	return &movePlan{
		p: p, a: *a, school: where, item: it, home: home, ownerUID: ownerUID, reason: reason, posted: posted,
		scheduled: newDay, newDay: newDay, fy: schooldirectory.OperationalFY(scheduledUTC),
		quarter: quarterOf(scheduledUTC), month: int(newDay.Month()), week: min(5, (newDay.Day()-1)/7+1),
		weeks: weeks, months: months, verdict: verdict, origin: origin, now: now,
		session: true, clusterName: clusterName,
	}, nil
}
