package activities

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
)

// visitNoticeTypes is apps.core.activity_types.VISIT_TYPES.
var visitNoticeTypes = []string{
	"school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "donor_visit",
	"story_gathering_visit", "school_invitation", "social_visit", "training_follow_up_visit",
	"in_school_coaching_visit", "core_visit", "core_assessment_visit", "baseline_ssa_visit",
	"school_visit_ssa_collection", "partner_ssa_collection",
}

const (
	scheduledVisitEvent = "school_visit_scheduled"
	scheduledVisitTitle = "School visit scheduled"
	planningCategory    = "planning"
	planNoticeLabel     = "View in My Plan"
	normalPriority      = "normal"
	activityContext     = "activity"
)

// NoticePush queues a notice's phone copy inside the notice's transaction.
type NoticePush func(ctx context.Context, tx pgx.Tx, notificationID, recipient string, now time.Time) error

// NoticePublisher tells the recipient's open pages about a notice.
type NoticePublisher interface {
	Publish(realtime.Event) realtime.Event
}

// WithOwnerNotices sets how the owner's notice reaches their phone and open
// pages. Without them the notice is still written to the inbox.
func (s *Service) WithOwnerNotices(push NoticePush, live NoticePublisher) *Service {
	s.noticePush, s.live = push, live
	return s
}

type scheduledNotice struct{ title, body, event string }

// ownerNotice is _notify_scheduled_owner's decision for a school visit:
// nobody is told about their own scheduling.
func ownerNotice(activityType, owner, actorUser, actorStaff, where string, day time.Time) (scheduledNotice, bool) {
	if !in(visitNoticeTypes, activityType) || owner == "" || owner == actorUser || owner == actorStaff {
		return scheduledNotice{}, false
	}
	return scheduledNotice{
		title: scheduledVisitTitle,
		body:  fmt.Sprintf("%s on %s.", where, day.Format("2 Jan 2006")),
		event: scheduledVisitEvent,
	}, true
}

// colleagueConfirmation is the view's answer when the visit lands on someone
// else's My Plan: it says whose, and links to the Calendar, which shows it.
func colleagueConfirmation(owner string, day time.Time) (message, planURL, label string) {
	return fmt.Sprintf("School visit scheduled onto %s's My Plan, because the "+
			"responsible staff member comes from the school's owner.", owner),
		fmt.Sprintf("/calendar?month=%d&year=%d", int(day.Month()), day.Year()), "Open the Calendar"
}

// staffName is the name of the person a staff profile belongs to, or the
// view's stand-in when there is none.
func staffName(ctx context.Context, q Querier, staffID string) (string, error) {
	var name *string
	err := q.QueryRow(ctx, `SELECT u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = $1`,
		staffID).Scan(&name)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && (name == nil || *name == "")) {
		return "the school's CCEO", nil
	}
	if err != nil {
		return "", fmt.Errorf("activities: reading the owner's name: %w", err)
	}
	return *name, nil
}

// tellScheduledOwner writes the owner's notice and its audit row. A notice
// never undoes scheduling, so the caller only logs a failure.
func (s *Service) tellScheduledOwner(ctx context.Context, pl *plan) error {
	r := pl.row
	notice, ok := ownerNotice(r.activityType, r.responsible, pl.p.UserID, pl.p.StaffProfileID, pl.school.Name, r.plannedDate)
	if !ok {
		return nil
	}
	now := s.now()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("activities: opening the owner's notice: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var notificationID, recipient string
	err = tx.QueryRow(ctx, `SELECT out_notification_id, out_recipient_id
  FROM gateway_notifications.notify_workflow($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
		cuid.New(), r.responsible, notice.title, notice.body, planningCategory, activityContext, r.id,
		"/my-plan/"+r.id, planNoticeLabel, normalPriority, notice.event, now).Scan(&notificationID, &recipient)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("activities: delivering the owner's notice: %w", err)
	}
	if s.noticePush != nil {
		if err := s.noticePush(ctx, tx, notificationID, recipient, now); err != nil {
			s.logger.WarnContext(ctx, "activities: the phone copy was not queued", "activity", r.id, "err", err)
		}
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "notification." + notice.event, SubjectKind: audit.Text(activityContext), SubjectID: audit.Text(r.id),
		Success: true, IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
		Payload: map[string]any{
			"category": planningCategory, "priority": normalPriority,
			"recipient_ids": []any{recipient}, "notification_ids": []any{notificationID},
		},
	}, now); err != nil {
		return fmt.Errorf("activities: auditing the owner's notice: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the owner's notice: %w", err)
	}
	if s.live != nil {
		s.live.Publish(realtime.Event{
			Type: "notification." + notice.event, EntityType: activityContext, EntityID: r.id,
			TargetUserID: recipient, ActorUserID: pl.p.UserID,
		})
	}
	return nil
}
