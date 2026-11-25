package activities

import (
	"context"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"log/slog"
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

type scheduledNotice struct {
	title, body, event, category, contextType, route, label, recipient string
	// priority is "normal" unless the trigger asks otherwise.
	priority string
}

func (n scheduledNotice) level() string {
	if n.priority == "" {
		return normalPriority
	}
	return n.priority
}

// ownerNotice is _notify_scheduled_owner's decision for a school visit:
// nobody is told about their own scheduling.
func ownerNotice(activityType, owner, actorUser, actorStaff, where string, day time.Time) (scheduledNotice, bool) {
	if !in(visitNoticeTypes, activityType) || owner == "" || owner == actorUser || owner == actorStaff {
		return scheduledNotice{}, false
	}
	return scheduledNotice{
		title: scheduledVisitTitle,
		body:  fmt.Sprintf("%s on %s.", where, day.Format("2 Jan 2006")),
		event: scheduledVisitEvent, category: planningCategory, contextType: activityContext,
		label: planNoticeLabel, recipient: owner,
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
// stand-in the caller's sentence uses when there is none.
func staffName(ctx context.Context, q Querier, staffID, standIn string) (string, error) {
	var name *string
	err := q.QueryRow(ctx, `SELECT u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = $1`,
		staffID).Scan(&name)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && (name == nil || *name == "")) {
		return standIn, nil
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
	notice.route = "/my-plan/" + r.id
	return s.deliverNotice(ctx, pl, notice)
}

// deliverNotice is WorkflowNotificationService.trigger for one recipient: the
// notice, its phone copy, its audit row, and a word to their open pages.
func (s *Service) deliverNotice(ctx context.Context, pl *plan, notice scheduledNotice) error {
	return s.sendNotice(ctx, pl.row.id, pl.p.UserID, pl.origin, notice)
}

// sendNotice is one notice about contextID, from actorID's save.
func (s *Service) sendNotice(ctx context.Context, contextID, actorID string, origin Origin, notice scheduledNotice) error {
	return workflowNotices{db: s.db, push: s.noticePush, live: s.live, logger: s.logger}.send(ctx, s.now(), contextID, actorID, origin, notice)
}

// workflowNotices is WorkflowNotificationService.trigger's delivery: the
// notice, its phone copy, its audit row, and a word to the recipient's pages.
type workflowNotices struct {
	db     *pgxpool.Pool
	push   NoticePush
	live   NoticePublisher
	logger *slog.Logger
}

// send is one notice about contextID, from actorID.
func (w workflowNotices) send(ctx context.Context, now time.Time, contextID, actorID string, origin Origin, notice scheduledNotice) error {
	return w.sendTo(ctx, now, contextID, actorID, origin, notice, []noticeRecipient{
		{id: notice.recipient, route: notice.route, label: notice.label},
	})
}

// noticeRecipient is one person told, with the link their role opens.
type noticeRecipient struct {
	id, route, label string
}

// sendTo is one trigger to several people: a notice each, one audit row
// naming every notice made, and a word to each one's open pages.
func (w workflowNotices) sendTo(ctx context.Context, now time.Time, contextID, actorID string, origin Origin,
	notice scheduledNotice, recipients []noticeRecipient) error {
	tx, err := w.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("activities: opening the notice: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	people, err := w.deliverInTx(ctx, tx, now, contextID, origin, notice, recipients)
	if err != nil || len(people) == 0 {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the notice: %w", err)
	}
	if w.live != nil {
		for _, recipient := range people {
			w.live.Publish(realtime.Event{
				Type: "notification." + notice.event, EntityType: notice.contextType, EntityID: contextID,
				TargetUserID: recipient, ActorUserID: actorID,
			})
		}
	}
	return nil
}

// deliverInTx writes the notices, their phone copies and the audit row in
// the caller's transaction, and says who was told.
func (w workflowNotices) deliverInTx(ctx context.Context, tx pgx.Tx, now time.Time, contextID string, origin Origin,
	notice scheduledNotice, recipients []noticeRecipient) ([]string, error) {
	var made, told []any
	var people []string
	for _, r := range recipients {
		var notificationID, recipient string
		err := tx.QueryRow(ctx, `SELECT out_notification_id, out_recipient_id
  FROM gateway_notifications.notify_workflow($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
			cuid.New(), r.id, notice.title, notice.body, notice.category, notice.contextType, nilIfEmpty(contextID),
			r.route, r.label, notice.level(), notice.event, now).Scan(&notificationID, &recipient)
		if errors.Is(err, pgx.ErrNoRows) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("activities: delivering the notice: %w", err)
		}
		if w.push != nil {
			if err := w.push(ctx, tx, notificationID, recipient, now); err != nil && w.logger != nil {
				w.logger.WarnContext(ctx, "activities: the phone copy was not queued", "context", contextID, "err", err)
			}
		}
		made, told, people = append(made, notificationID), append(told, recipient), append(people, recipient)
	}
	if len(made) == 0 {
		return nil, nil
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "notification." + notice.event, SubjectKind: audit.Text(notice.contextType), SubjectID: audit.Text(contextID),
		Success: true, IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent),
		CorrelationID: nilIfEmpty(origin.CorrelationID),
		Payload: map[string]any{
			"category": notice.category, "priority": notice.level(), "recipient_ids": told, "notification_ids": made,
		},
	}, now); err != nil {
		return nil, fmt.Errorf("activities: auditing the notice: %w", err)
	}
	return people, nil
}

// NotifyInTx is SendNotices inside the caller's transaction, for work that
// commits with its notices (an outbox handler): it says who was told, so the
// caller can word their pages once it commits.
func NotifyInTx(ctx context.Context, tx pgx.Tx, push NoticePush, logger *slog.Logger, now time.Time,
	contextID string, n Notice, to []NoticeTo) ([]string, error) {
	return workflowNotices{push: push, logger: logger}.deliverInTx(ctx, tx, now, contextID, Origin{}, noticeOf(n), recipientsOf(to))
}

func noticeOf(n Notice) scheduledNotice {
	return scheduledNotice{title: n.Title, body: n.Body, event: n.Event, category: n.Category, contextType: n.ContextType,
		priority: n.Priority}
}

func recipientsOf(to []NoticeTo) []noticeRecipient {
	recipients := make([]noticeRecipient, 0, len(to))
	for _, t := range to {
		recipients = append(recipients, noticeRecipient{id: t.UserID, route: t.Route, label: t.Label})
	}
	return recipients
}

// Notice is a workflow notification another package sends.
type Notice struct {
	Title, Body, Event, Category, ContextType, Priority string
}

// NoticeTo is one person told, with the link their role opens.
type NoticeTo struct {
	UserID, Route, Label string
}

// SendNotices is WorkflowNotificationService.trigger for another package's
// save: a notice each, its phone copy, one audit row naming every notice,
// and a word to each one's open pages.
func SendNotices(ctx context.Context, db *pgxpool.Pool, push NoticePush, live NoticePublisher, logger *slog.Logger, now time.Time,
	contextID, actorID string, origin Origin, n Notice, to []NoticeTo) error {
	return workflowNotices{db: db, push: push, live: live, logger: logger}.sendTo(ctx, now, contextID, actorID, origin,
		noticeOf(n), recipientsOf(to))
}
