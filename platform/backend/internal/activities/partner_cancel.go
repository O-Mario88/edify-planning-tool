package activities

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// A partner calling off its own dated work from My Plan's Cancel drawer
// (my_plan_views.cancel_activity_action over services._cancel_or_defer):
// the activity cancelled and its money withdrawn as a staff visit's is, and
// the scheduling it stood for undone (partners.services.
// undo_assignment_scheduling): a date the partner put on it goes and the
// hand-over waits for the partner again, a booking staff made is closed.
// The partner is told. Staff cancelling a partner's work stays the existing
// application's.

const (
	handOverReopened      = "reopened"
	handOverClosed        = "closed"
	supportClosed         = "support_closed"
	handOverReturnMax     = 300
	partnerCancelEvent    = "partner_booking_cancelled"
	partnerCancelTitle    = "A booking you hold has been cancelled"
	partnerStillTheirs    = " The school is still assigned to you: schedule it again from Assigned Activities."
	partnerActivityLabel  = "Open Activity"
	partnerCancelCategory = "activity"
)

// scheduledHandOverStatuses are PartnerAssignment.SCHEDULED_STATUSES.
var scheduledHandOverStatuses = []string{"partner_scheduled", "scheduled", "completed"}

// PartnerCancelRequest is a partner login's cancel: the activity, the reason,
// and the organisations the login acts for (resolve_partner_ids).
type PartnerCancelRequest struct {
	ActivityID, Reason string
	PartnerIDs         []string
}

// partnerWork is the partner's activity as its cancel reads it.
type partnerWork struct {
	moved
	partner, datedBy, name, place, schoolType, monitor string
	paired, other, hasScheduled                        bool
}

// readPartnerWork is the partner's own dated work at a school that is not a
// Core school, or nil for any other.
func readPartnerWork(ctx context.Context, q Querier, id string, partners []string) (*partnerWork, error) {
	var w partnerWork
	var planned, scheduled *time.Time
	var batch string
	err := q.QueryRow(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.school_id, ''),
       COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.daily_visit_batch_id, ''),
       a.planned_date, a.scheduled_date,
       COALESCE(a.assigned_partner_id, ''), COALESCE(a.partner_date_set_by, ''), COALESCE(a.activity_name_snapshot, ''),
       COALESCE(s.name, ''), COALESCE(s.school_type, ''),
       (a.paired_school_visit_id IS NOT NULL OR EXISTS (SELECT 1 FROM activity o WHERE o.paired_school_visit_id = a.id)),
       (a.cluster_id IS NOT NULL OR a.project_id IS NOT NULL OR a.end_date IS NOT NULL)
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.id = $1 AND a.deleted_at IS NULL AND a.delivery_type = 'partner' AND a.assigned_partner_id = ANY($2)`,
		id, partners).Scan(&w.id, &w.activityType, &w.status, &w.schoolID, &w.responsible, &w.monitor, &batch, &planned, &scheduled,
		&w.partner, &w.datedBy, &w.name, &w.place, &w.schoolType, &w.paired, &w.other)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the partner's work: %w", err)
	}
	if w.other || w.schoolID == "" || in(rules.Gate.CoreRuleTypes, w.schoolType) || batch != "" || planned == nil {
		return nil, nil
	}
	w.batchID, w.plannedDate = batch, *planned
	if scheduled != nil {
		w.scheduled = *scheduled
	}
	w.hasScheduled = scheduled != nil
	return &w, nil
}

// partnerDated is dating_policy.partner_has_dated.
func (w *partnerWork) partnerDated() bool {
	return w.status != "assigned_to_partner" && w.datedBy != "staff"
}

// CancelPartnerWork calls the partner's work off, or refuses it in the
// existing words (with the view's failure row), or hands it on (ErrHandOn).
// The caller has refused a team member and asked can_view_record.
func (s *Service) CancelPartnerWork(ctx context.Context, p auth.Principal, req PartnerCancelRequest, origin Origin) (CancelAnswer, error) {
	if p.InActingAppointment || len(req.PartnerIDs) == 0 {
		return CancelAnswer{}, handOn("not a partner login cancelling its own work")
	}
	w, err := readPartnerWork(ctx, s.db, strings.TrimSpace(req.ActivityID), req.PartnerIDs)
	if err != nil {
		return CancelAnswer{}, err
	}
	if w == nil || w.paired {
		return CancelAnswer{}, handOn("not the partner's own dated work at a school, or one half of a pair")
	}
	pl, err := s.partnerCancelChecks(ctx, p, w, req, origin)
	var refusal *Refusal
	if errors.As(err, &refusal) && pl != nil {
		s.auditCancel(ctx, pl, false, refusal.Message)
	}
	if err != nil {
		return CancelAnswer{}, err
	}
	rowID, outcome, err := s.writePartnerCancel(ctx, pl, w)
	if errors.As(err, &refusal) {
		s.auditCancel(ctx, pl, false, refusal.Message)
	}
	if err != nil {
		return CancelAnswer{}, err
	}
	s.tellPartnerOfCancel(ctx, pl, w, outcome)
	s.afterCancel(ctx, pl, rowID)
	return CancelAnswer{ActivityID: w.id, Status: "cancelled", Reason: pl.reason, Message: rules.Move.SavedMessage}, nil
}

// partnerCancelChecks is the reason, the notices and the money, as for a
// staff visit.
func (s *Service) partnerCancelChecks(ctx context.Context, p auth.Principal, w *partnerWork, req PartnerCancelRequest, origin Origin) (*cancelPlan, error) {
	pl := &cancelPlan{p: p, a: w.moved, reason: strings.TrimSpace(req.Reason), origin: origin, now: s.now()}
	if pl.reason == "" {
		return pl, refuse("%s", cancelReasonRequired)
	}
	if utf8.RuneCountInString(pl.reason) > maxCancelReason {
		return nil, handOn("a reason longer than the activity keeps")
	}
	if why, err := moveNotices(ctx, s.db, w.id, ""); err != nil || why != "" {
		if err != nil {
			return nil, err
		}
		return nil, handOn(why)
	}
	// settle_day_off_alerts brings the work's owner's notices up to date: a
	// day-off notice open for anyone the work could be read as owned by is
	// handed on.
	var dayOff bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE source_event_type = $1 AND resolved_at IS NULL
  AND (recipient_id = $2 OR recipient_id IN (SELECT user_id FROM staff_profile WHERE id = ANY($3))
       OR recipient_id IN (SELECT user_id FROM partner WHERE id = $4)))`,
		rules.Move.DayOffEvent, p.UserID, []string{w.responsible, w.monitor}, w.partner).Scan(&dayOff); err != nil {
		return nil, fmt.Errorf("activities: reading the work's day-off notices: %w", err)
	}
	if dayOff {
		return nil, handOn("an open day-off notice")
	}
	asker, ok := s.pricing.(CancelPricing)
	if !ok {
		return nil, fmt.Errorf("activities: the pricing cannot check a cancel")
	}
	verdict, err := asker.CancelCheck(ctx, w.id, pl.reason)
	if err != nil {
		return nil, err
	}
	if !verdict.Found || verdict.FrozenWeeks || verdict.Credited || verdict.PricedHere {
		return nil, handOn("the cancel's money writes after commit, or prices in the save")
	}
	pl.verdict = verdict
	if verdict.Refusal != "" {
		return pl, &Refusal{Message: verdict.Refusal}
	}
	return pl, nil
}

// writePartnerCancel is the cancel's transaction with the hand-over's undo.
func (s *Service) writePartnerCancel(ctx context.Context, pl *cancelPlan, w *partnerWork) (int64, string, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, "", fmt.Errorf("activities: opening the cancel: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := s.cancelInTx(ctx, tx, pl); err != nil {
		return 0, "", err
	}
	outcome, err := s.undoHandOverScheduling(ctx, tx, pl, w)
	if err != nil {
		return 0, "", err
	}
	rowID, err := keepCancelCosts(ctx, tx, pl)
	if err != nil {
		return 0, "", err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, "", fmt.Errorf("activities: committing the cancel: %w", err)
	}
	return rowID, outcome, nil
}

// undoHandOverScheduling is undo_assignment_scheduling: the hand-over the
// work was dated from waits for the partner again where the partner dated
// it and no other waits beside it; otherwise it is closed. "" for none.
func (s *Service) undoHandOverScheduling(ctx context.Context, tx pgx.Tx, pl *cancelPlan, w *partnerWork) (string, error) {
	var id, status, school, partner, schoolName, partnerName, purpose, support, visit, training, course string
	var day *time.Time
	var outside bool
	err := tx.QueryRow(ctx, `SELECT h.id, h.status, h.scheduled_date, COALESCE(h.school_id, ''), COALESCE(h.partner_id, ''),
  COALESCE(sc.name, ''), COALESCE(pa.name, ''), COALESCE(h.purpose_of_visit, ''), COALESCE(h.support_type, ''),
  COALESCE(h.visit_number, ''), COALESCE(h.training_number, ''), COALESCE(h.training_course_id, ''), h.outside_ssa
FROM partner_assignment h LEFT JOIN school sc ON sc.id = h.school_id LEFT JOIN partner pa ON pa.id = h.partner_id
WHERE h.scheduled_activity_id = $1 LIMIT 1 FOR UPDATE OF h`, w.id).Scan(&id, &status, &day, &school, &partner,
		&schoolName, &partnerName, &purpose, &support, &visit, &training, &course, &outside)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("activities: reading the work's hand-over: %w", err)
	}
	if !in(scheduledHandOverStatuses, status) {
		return "", nil
	}
	var waiting bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment WHERE school_id = $1 AND partner_id = $2
  AND status = ANY($3) AND NOT outside_ssa AND NOT $8
  AND (COALESCE(purpose_of_visit, '') = $4) = ($5 = $4)
  AND COALESCE(support_type, '') = $6 AND COALESCE(visit_number, '') = $7 AND COALESCE(training_number, '') = $9)`,
		school, partner, []string{handOverAssigned, handOverOpenStatus}, ssaSupportPurpose, purpose, support, visit, outside,
		training).Scan(&waiting); err != nil {
		return "", fmt.Errorf("activities: reading the partner's waiting hand-overs: %w", err)
	}
	if outside {
		return "", handOn("a hand-over of a project no SSA intervention measures")
	}
	var before any
	if day != nil {
		before = day.Format(time.DateOnly)
	}
	outcome := handOverClosed
	if w.partnerDated() && !waiting {
		outcome = handOverReopened
		_, err = tx.Exec(ctx, `UPDATE partner_assignment SET status = $2, scheduled_date = NULL, scheduled_activity_id = NULL,
  training_course_id = COALESCE(training_course_id, (SELECT training_course_id FROM activity WHERE id = $3)), updated_at = $4
WHERE id = $1`, id, handOverOpenStatus, w.id, pl.now)
	} else {
		_, err = tx.Exec(ctx, `UPDATE partner_assignment SET status = $2, scheduled_date = NULL, scheduled_activity_id = NULL,
  returned_at = $3, return_reason = $4, resolution = $5, resolution_note = 'Closed with the cancelled activity.',
  resolved_at = $3, resolved_by = $6, updated_at = $3 WHERE id = $1`,
			id, handOverReturned, pl.now, truncateRunes(strings.TrimSpace("The booking was cancelled. "+pl.reason), handOverReturnMax),
			supportClosed, optString(pl.p.UserID))
	}
	if err != nil {
		return "", fmt.Errorf("activities: undoing the hand-over's scheduling: %w", err)
	}
	after := handOverOpenStatus
	if outcome == handOverClosed {
		after = handOverReturned
	}
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, pl.now)
	if err != nil {
		return "", err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "partner_assignment.scheduling_" + outcome, SubjectKind: audit.Text("PartnerAssignment"), SubjectID: audit.Text(id),
		ActorID: audit.Text(pl.p.UserID), Success: true,
		Payload: withStamps(map[string]any{
			"before": map[string]any{"status": status, "scheduledDate": before, "activityId": w.id},
			"after":  map[string]any{"status": after}, "school": schoolName, "partner": partnerName, "reason": pl.reason,
		}, cover),
	}, pl.now); err != nil {
		return "", fmt.Errorf("activities: writing the hand-over's audit row: %w", err)
	}
	return outcome, nil
}

// tellPartnerOfCancel is _notify_partner_schedule_change: the partner's
// login told what was called off, and that the school is still theirs when
// the hand-over waits again. It never blocks the cancel.
func (s *Service) tellPartnerOfCancel(ctx context.Context, pl *cancelPlan, w *partnerWork, outcome string) {
	var user string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(user_id, '') FROM partner WHERE id = $1 AND deleted_at IS NULL`, w.partner).Scan(&user); err != nil || user == "" {
		return
	}
	work := w.name
	if work == "" {
		work = w.activityType
		if label, ok := rules.PartnerInvoice.ActivityTypeLabels[w.activityType]; ok {
			work = label
		}
	}
	body := strings.TrimSpace(fmt.Sprintf("%s for %s on %s has been cancelled. %s", work, w.place,
		w.plannedDate.Format("2 Jan 2006"), pl.reason))
	if outcome == handOverReopened {
		body += partnerStillTheirs
	}
	notice := scheduledNotice{title: partnerCancelTitle, body: body, event: partnerCancelEvent, category: partnerCancelCategory,
		priority: highPriority, contextType: "Activity", route: "/my-plan/" + w.id, label: partnerActivityLabel, recipient: user}
	if err := s.sendNotice(ctx, w.id, pl.p.UserID, pl.origin, notice); err != nil {
		s.logger.Warn("activities: the partner was not told of the cancel", "activity", w.id, "err", err)
	}
}

// RecordCancelDenied is the view's unauthorized_mutation_attempt row for a
// cancel of work outside the reader's reach (my_plan_views.
// cancel_activity_action), with the stamps log() adds.
func (s *Service) RecordCancelDenied(ctx context.Context, p auth.Principal, activityID string, origin Origin) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, p.UserID, s.now())
	if err != nil {
		return err
	}
	var payload any
	if cover != nil {
		payload = withStamps(map[string]any{}, cover)
	}
	role := p.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "unauthorized_mutation_attempt", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(activityID),
		ActorID: audit.Text(p.UserID), ActorRole: &role, Success: false,
		Reason: audit.Text("User attempted to cancel an activity outside their scoped schools/ownership."), Payload: payload,
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
