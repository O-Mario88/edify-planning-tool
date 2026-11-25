package plreview

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
)

const (
	notYourOfficer = "Access Denied: You do not supervise the owner of this activity."
	notThisPage    = "Access Denied: Your active role does not have permission to view Pl Review Queue."
	needsReason    = "Say what needs correcting before returning a completion."
	noLongerWaits  = "This completion is no longer waiting for Programme Lead review."
	noSalesforceID = "This completion has no Salesforce ID. Return it to the officer to enter the ID; it cannot be verified without one."
)

// ReviewRefusal is a business-rule refusal on PL approve/return.
type ReviewRefusal struct {
	Message   string
	Forbidden bool
	NotFound  bool
}

func (r *ReviewRefusal) Error() string { return r.Message }

// ReviewResult is the outcome of a PL approve or return decision.
type ReviewResult struct {
	ActivityID string
	Status     string
	Reason     string
}

// Publisher tells a person's open pages that something changed.
type Publisher interface {
	Publish(realtime.Event) realtime.Event
}

// ReviewService performs Programme Lead completion approvals and returns
// natively in Go via gateway_pl_review.* without calling Django.
type ReviewService struct {
	pool           *pgxpool.Pool
	now            func() time.Time
	live           Publisher
	salesforceSync bool
	push           PushReadiness
	logger         *slog.Logger
}

// NewReviewService builds a ReviewService over pool.
func NewReviewService(pool *pgxpool.Pool, now func() time.Time) *ReviewService {
	if now == nil {
		now = time.Now
	}
	return &ReviewService{pool: pool, now: now, logger: slog.Default()}
}

// WithRealtime tells the officer's open pages when a decision reaches them.
func (s *ReviewService) WithRealtime(live Publisher) *ReviewService {
	s.live = live
	return s
}

// WithSalesforceSync queues the Salesforce sync of approved work
// (SALESFORCE_SYNC_ENABLED, the existing application's switch).
func (s *ReviewService) WithSalesforceSync(on bool) *ReviewService {
	s.salesforceSync = on
	return s
}

// WithPush names the push services this deployment can send through.
func (s *ReviewService) WithPush(ready PushReadiness) *ReviewService {
	s.push = ready
	return s
}

// WithLogger names where a follow-up that failed after the decision is told.
func (s *ReviewService) WithLogger(logger *slog.Logger) *ReviewService {
	if logger != nil {
		s.logger = logger
	}
	return s
}

// canReviewRole is who may decide at all: the page holds Admin, Impact
// Assessment and the lead, and can_review_activity then refuses Impact
// Assessment, which verifies partner work elsewhere.
func canReviewRole(role string) bool {
	return role == rules.LeadRole || role == rules.AdminRole
}

// checkReviewable is the decision views' doors, in their order: the page, the
// record, this reviewer's hold on it, and whether it is still waiting.
func (s *ReviewService) checkReviewable(ctx context.Context, tx pgx.Tx, p auth.Principal, activityID string) (Review, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return Review{}, &ReviewRefusal{Message: notThisPage, Forbidden: true}
	}
	review, err := decidable(ctx, tx, p, activityID, s.now())
	if err != nil {
		return Review{}, err
	}
	if !canReviewRole(p.ActiveRole) {
		return Review{}, &ReviewRefusal{Message: notYourOfficer, Forbidden: true}
	}
	return review, nil
}

// reviewNotice is what the officer is told.
type reviewNotice struct {
	event, title, body, label, priority string
}

// Approve is apps.pl_review.services.confirm and the view around it. In one
// transaction: the approval, the recommendations it settles, a loan-use visit's
// link, the visit's SSA, the notices it closes, the events it raises and its
// audit row. Then, as the existing order has it, milestone progress, the
// officer's notice, the view's audit row and the ledger's marks, none of which
// can undo it.
func (s *ReviewService) Approve(ctx context.Context, p auth.Principal, activityID string) (ReviewResult, error) {
	if strings.TrimSpace(activityID) == "" {
		return ReviewResult{}, &ReviewRefusal{Message: "Activity is required."}
	}
	now := s.now().UTC().Truncate(time.Microsecond)
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: starting approve tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	target, err := s.checkReviewable(ctx, tx, p, activityID)
	if err != nil {
		return ReviewResult{}, err
	}
	progress, err := planProgress(ctx, tx, target)
	if err != nil {
		return ReviewResult{}, err
	}
	var verdict string
	if err := tx.QueryRow(ctx, `SELECT gateway_pl_review.approve_completion($1, $2, $3)`,
		activityID, p.UserID, now).Scan(&verdict); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: approve_completion: %w", err)
	}
	switch verdict {
	case "":
	case "no_sfid":
		return ReviewResult{}, &ReviewRefusal{Message: noSalesforceID}
	case "changed":
		return ReviewResult{}, &ReviewRefusal{Message: noLongerWaits}
	default:
		return ReviewResult{}, fmt.Errorf("plreview: unexpected approve verdict %q", verdict)
	}
	if err := settleRecommendations(ctx, tx, target, now); err != nil {
		return ReviewResult{}, err
	}
	if err := linkLoanVisit(ctx, tx, activityID, now); err != nil {
		return ReviewResult{}, err
	}
	ssaMarks, err := confirmVisitSSA(ctx, tx, target, p.UserID, now)
	if err != nil {
		return ReviewResult{}, err
	}
	if err := closeNotice(ctx, tx, eventAwaitingLead, "Activity", activityID, now); err != nil {
		return ReviewResult{}, err
	}
	if target.Status == statusAwaitingIA {
		if err := closeNotice(ctx, tx, eventAwaitingIA, "activity", activityID, now); err != nil {
			return ReviewResult{}, err
		}
	}
	if err := raiseEvents(ctx, tx, reviewEvents(target, statusVerified, now, s.salesforceSync), now); err != nil {
		return ReviewResult{}, err
	}
	if err := appendAudit(ctx, tx, decisionAudit(ctx, p, "pl_review_confirm", target, statusVerified, ""), now); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: appending approve audit: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: committing approve: %w", err)
	}
	if err := s.recordProgress(ctx, activityID, progress, now); err != nil {
		s.logger.ErrorContext(ctx, "plreview: the milestone credit was not recorded", "activity", activityID, "err", err)
	}
	s.afterDecision(ctx, p, target, reviewNotice{
		event: eventVerifiedByPL, title: "Your completion was approved and verified",
		body:  "Your Program Lead approved and verified your activity completion and evidence.",
		label: "Open Activity", priority: "normal",
	}, "pl_approve_completion", nil, ssaMarks, now)
	return ReviewResult{ActivityID: activityID, Status: statusVerified}, nil
}

// Return is apps.pl_review.services.return_activity and the view around it:
// the reasons ticked and what the lead wrote, read by the officer as one note.
func (s *ReviewService) Return(ctx context.Context, p auth.Principal, activityID string, reasons []string, written string) (ReviewResult, error) {
	written = strings.TrimSpace(written)
	note := composeReturnNote(reasons, written)
	if note == "" {
		return ReviewResult{}, &ReviewRefusal{Message: needsReason}
	}
	if strings.TrimSpace(activityID) == "" {
		return ReviewResult{}, &ReviewRefusal{Message: "Activity is required."}
	}
	now := s.now().UTC().Truncate(time.Microsecond)
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: starting return tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	target, err := s.checkReviewable(ctx, tx, p, activityID)
	if err != nil {
		return ReviewResult{}, err
	}
	var verdict string
	if err := tx.QueryRow(ctx, `SELECT gateway_pl_review.return_completion($1, $2, $3, $4)`,
		activityID, p.UserID, note, now).Scan(&verdict); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: return_completion: %w", err)
	}
	switch verdict {
	case "":
	case "no_reason":
		return ReviewResult{}, &ReviewRefusal{Message: needsReason}
	case "changed":
		return ReviewResult{}, &ReviewRefusal{Message: noLongerWaits}
	default:
		return ReviewResult{}, fmt.Errorf("plreview: unexpected return verdict %q", verdict)
	}
	if err := linkLoanVisit(ctx, tx, activityID, now); err != nil {
		return ReviewResult{}, err
	}
	if err := closeNotice(ctx, tx, eventAwaitingLead, "Activity", activityID, now); err != nil {
		return ReviewResult{}, err
	}
	if err := raiseEvents(ctx, tx, reviewEvents(target, statusReturnedByPL, now, s.salesforceSync), now); err != nil {
		return ReviewResult{}, err
	}
	if err := appendAudit(ctx, tx, decisionAudit(ctx, p, "pl_review_return", target, statusReturnedByPL, note), now); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: appending return audit: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: committing return: %w", err)
	}
	s.afterDecision(ctx, p, target, reviewNotice{
		event: eventReturnedByPL, title: "Your completion was returned", body: note,
		label: "Fix and Resubmit", priority: "high",
	}, "pl_return_completion", map[string]any{"reason": returnAuditReason(reasons, written)}, nil, now)
	return ReviewResult{ActivityID: activityID, Status: statusReturnedByPL, Reason: note}, nil
}

func closeNotice(ctx context.Context, tx pgx.Tx, event, contextType, activityID string, now time.Time) error {
	if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, $2, $3, $4)`,
		event, contextType, activityID, now); err != nil {
		return fmt.Errorf("plreview: closing the %s notice: %w", event, err)
	}
	return nil
}

func raiseEvents(ctx context.Context, tx pgx.Tx, events []outboxEvent, now time.Time) error {
	for _, event := range events {
		payload, err := json.Marshal(event.Payload)
		if err != nil {
			return fmt.Errorf("plreview: encoding the %s event: %w", event.Type, err)
		}
		if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.enqueue_event($1, $2, $3::jsonb, $4, $5)`,
			cuid.New(), event.Type, string(payload), event.Key, now); err != nil {
			return fmt.Errorf("plreview: raising the %s event: %w", event.Type, err)
		}
	}
	return nil
}

// orNil is a value as the existing payloads carry it: an absent id is null.
func orNil(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func stamped(ctx context.Context, entry audit.Entry) audit.Entry {
	if from, ok := origin.From(ctx); ok {
		entry.IPAddress, entry.UserAgent, entry.CorrelationID = audit.Text(from.IP), audit.Text(from.UserAgent), audit.Text(from.CorrelationID)
	}
	entry.Success = true
	return entry
}

func appendAudit(ctx context.Context, tx pgx.Tx, entry audit.Entry, now time.Time) error {
	_, err := audit.Append(ctx, tx, entry, now)
	return err
}

// decisionAudit is the service's _audit row.
func decisionAudit(ctx context.Context, p auth.Principal, action string, r Review, status, reason string) audit.Entry {
	return stamped(ctx, audit.Entry{
		Action: action, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(r.ID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Reason: audit.Text(reason),
		Payload: map[string]any{
			"schoolId":           orNil(r.SchoolID),
			"activityType":       r.ActivityType,
			"responsibleStaffId": orNil(r.ResponsibleStaffID),
			"status":             status,
		},
	})
}

// afterDecision is what follows the commit. The decision stands whatever
// happens here, so a failure is reported and goes no further.
func (s *ReviewService) afterDecision(ctx context.Context, p auth.Principal, r Review, notice reviewNotice, viewAction string, viewPayload any, marks []ledgerMark, now time.Time) {
	if err := s.tellOfficer(ctx, r, notice, p, now); err != nil {
		s.logger.WarnContext(ctx, "plreview: the officer was not told", "activity", r.ID, "err", err)
	}
	entry := stamped(ctx, audit.Entry{
		Action: viewAction, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(r.ID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Payload: viewPayload,
	})
	if err := s.inTransaction(ctx, func(tx pgx.Tx) error { return appendAudit(ctx, tx, entry, now) }); err != nil {
		s.logger.WarnContext(ctx, "plreview: the decision's audit row was not written", "activity", r.ID, "err", err)
	}
	if err := s.markLedger(ctx, r, marks, now); err != nil {
		s.logger.WarnContext(ctx, "plreview: the target ledger was not marked", "activity", r.ID, "err", err)
	}
}

func (s *ReviewService) inTransaction(ctx context.Context, work func(pgx.Tx) error) error {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := work(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// tellOfficer is _notify_after_review: one notice to whoever owns the work,
// its audit row, and a word to their open pages.
func (s *ReviewService) tellOfficer(ctx context.Context, r Review, notice reviewNotice, p auth.Principal, now time.Time) error {
	if r.Owner == "" {
		return nil
	}
	var recipient string
	err := s.inTransaction(ctx, func(tx pgx.Tx) error {
		var notificationID string
		err := tx.QueryRow(ctx, `
SELECT out_notification_id, out_recipient_id
  FROM gateway_notifications.notify_workflow($1, $2, $3, $4, $5, 'Activity', $6, $7, $8, $9, $10, $11)`,
			cuid.New(), r.Owner, notice.title, notice.body, notificationCategory, r.ID, "/my-plan/"+r.ID,
			notice.label, notice.priority, notice.event, now).Scan(&notificationID, &recipient)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		if err != nil {
			return fmt.Errorf("delivering the notice: %w", err)
		}
		if err := s.queuePush(ctx, tx, notificationID, recipient, now); err != nil {
			s.logger.WarnContext(ctx, "plreview: the phone copy was not queued", "activity", r.ID, "err", err)
		}
		return appendAudit(ctx, tx, stamped(ctx, audit.Entry{
			Action: "notification." + notice.event, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(r.ID),
			Payload: map[string]any{
				"category": notificationCategory, "priority": notice.priority,
				"recipient_ids": []any{recipient}, "notification_ids": []any{notificationID},
			},
		}), now)
	})
	if err != nil {
		return err
	}
	if recipient != "" && s.live != nil {
		s.live.Publish(realtime.Event{
			Type: "notification." + notice.event, EntityType: "Activity", EntityID: r.ID,
			TargetUserID: recipient, ActorUserID: p.UserID,
		})
	}
	return nil
}

// markLedger marks the years the targets ledger must rebuild: the work's
// owner, for the kinds of work a target area counts, and each confirmed SSA's
// collector.
func (s *ReviewService) markLedger(ctx context.Context, r Review, marks []ledgerMark, now time.Time) error {
	if mark, ok := workMark(r); ok {
		marks = append(slices.Clone(marks), mark)
	}
	if len(marks) == 0 {
		return nil
	}
	return s.inTransaction(ctx, func(tx pgx.Tx) error {
		for _, mark := range marks {
			if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.mark_ledger($1, $2, $3)`, mark.owner, mark.fy, now); err != nil {
				return err
			}
		}
		return nil
	})
}
