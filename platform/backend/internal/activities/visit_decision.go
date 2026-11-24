package activities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// The school owner's decision on a visit someone else asked to make
// (apps.planning.visit_requests.approve and decline, through
// visit_request_views.visit_request_decide).

const (
	visitApproved        = "school_visit_approved"
	visitDeclined        = "school_visit_declined"
	visitRequestQueueURL = "/planning/visit-requests"
	decisionNoteLimit    = 512
	requestNotFound      = "Visit request not found."
	requestDecided       = "This visit request has already been decided."
	declineNeedsReason   = "Give the requester a reason for declining."
	notAllowedToDecide   = "You are not allowed to perform this action."
)

// visitRequestRoles are the roles with the visit_requests page (navigation).
var visitRequestRoles = []string{"CCEO", "Program Lead", "ProjectCoordinator", "CountryDirector", "ImpactAssessment",
	"Accountant", "Admin"}

// VisitDecision is the posted decision on one request.
type VisitDecision struct {
	ActivityID, Decision, Note string
}

// decidedVisit is the request as the decision reads it, under its lock.
type decidedVisit struct {
	id, status, owner, schoolID, schoolName, schoolType, activityType string
	responsible, purpose, fy, delivery                                string
	planned                                                           *time.Time
	scheduled                                                         bool
	otherShape                                                        bool
	universal                                                         bool
}

// visitDecisionWhere is _where: the school's name.
func visitDecisionWhere(name string) string {
	if name == "" {
		return "the school"
	}
	return name
}

// visitDecisionOn is _on: " on 7 Dec 2026".
func visitDecisionOn(planned *time.Time) string {
	if planned == nil {
		return ""
	}
	return " on " + planned.Format("2 Jan 2006")
}

func clip(text string, limit int) string {
	runes := []rune(text)
	if len(runes) > limit {
		return string(runes[:limit])
	}
	return text
}

// DecideVisitRequest makes the owner's decision, or refuses it in the
// existing words, or hands it on (ErrHandOn).
func (s *Service) DecideVisitRequest(ctx context.Context, p auth.Principal, d VisitDecision, origin Origin) (Answer, error) {
	if d.Decision != "approve" && d.Decision != "decline" {
		return Answer{}, handOn("an unknown decision")
	}
	if p.InActingAppointment || !in(visitRequestRoles, p.ActiveRole) {
		return Answer{}, handOn("not a role Go decides visit requests for")
	}
	note := strings.TrimSpace(d.Note)
	if d.Decision == "decline" && note == "" {
		return Answer{}, refuse(declineNeedsReason)
	}
	now := s.now()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return Answer{}, fmt.Errorf("activities: opening the decision: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	v, err := readDecidedVisit(ctx, tx, d.ActivityID)
	if err != nil {
		return Answer{}, err
	}
	if v == nil {
		return Answer{}, refuse(requestNotFound)
	}
	if v.status != awaitingOwnerApproval {
		return Answer{}, refuse(requestDecided)
	}
	if v.owner == "" || (v.owner != p.UserID && v.owner != p.StaffProfileID) {
		s.auditUnauthorizedDecision(ctx, p, v.id, origin)
		return Answer{}, &Refusal{Message: notAllowedToDecide, Forbidden: true}
	}
	var rowID int64
	if d.Decision == "approve" {
		if rowID, err = s.approveInTx(ctx, tx, p, v, note, now); err != nil {
			return Answer{}, err
		}
	} else if err := declineInTx(ctx, tx, p, v, note, now); err != nil {
		return Answer{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Answer{}, fmt.Errorf("activities: committing the decision: %w", err)
	}
	s.afterDecision(ctx, p, v, d.Decision, note, rowID, origin)
	where := visitDecisionWhere(v.schoolName)
	if d.Decision == "approve" {
		return Answer{ActivityID: v.id, Status: "scheduled",
			Message: fmt.Sprintf("Visit to %s approved. It is now on the requester's plan.", where)}, nil
	}
	return Answer{ActivityID: v.id, Status: "rejected",
		Message: fmt.Sprintf("Visit to %s declined. The requester has been told.", where)}, nil
}

func readDecidedVisit(ctx context.Context, tx pgx.Tx, id string) (*decidedVisit, error) {
	var v decidedVisit
	var owner, school, schoolName, schoolType, responsible, purpose, fy, delivery *string
	err := tx.QueryRow(ctx, `
SELECT a.id, a.status, a.approval_owner_id, a.school_id, s.name, s.school_type, a.activity_type,
       a.responsible_staff_id, a.purpose_type, a.fy, a.delivery_type, a.planned_date, a.scheduled_date IS NOT NULL,
       (a.cluster_id IS NOT NULL OR a.end_date IS NOT NULL OR a.paired_school_visit_id IS NOT NULL
        OR a.daily_visit_batch_id IS NOT NULL OR a.activity_type = 'core_visit'
        OR EXISTS (SELECT 1 FROM activity o WHERE o.paired_school_visit_id = a.id AND o.deleted_at IS NULL)),
       (a.project_id IS NOT NULL
        OR EXISTS (SELECT 1 FROM activity_catalogue_item c WHERE c.id IN (a.training_course_id, a.catalogue_item_id)
                    AND c.universal_training))
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.id = $1 AND a.deleted_at IS NULL FOR UPDATE OF a`, id).Scan(
		&v.id, &v.status, &owner, &school, &schoolName, &schoolType, &v.activityType, &responsible, &purpose, &fy,
		&delivery, &v.planned, &v.scheduled, &v.otherShape, &v.universal)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the visit request: %w", err)
	}
	v.owner, v.schoolID, v.schoolName, v.schoolType = text(owner), text(school), text(schoolName), text(schoolType)
	v.responsible, v.purpose, v.fy, v.delivery = text(responsible), text(purpose), text(fy), text(delivery)
	return &v, nil
}

// approveInTx is approve's transaction: the school's visit rule, the new
// status, the day it joins, and the costs it leaves to follow.
func (s *Service) approveInTx(ctx context.Context, tx pgx.Tx, p auth.Principal, v *decidedVisit, note string, now time.Time) (int64, error) {
	if v.otherShape || v.schoolType == "core" || v.delivery != "staff" || !v.scheduled || v.planned == nil {
		return 0, handOn("a request Go does not approve (its shape, its school or its delivery)")
	}
	if err := clientPoolOpen(ctx, tx, v, now); err != nil {
		return 0, err
	}
	if _, err := tx.Exec(ctx, `UPDATE activity SET status = 'scheduled', owner_decided_at = $2, owner_decided_by = $3,
  owner_decision_note = $4, updated_at = $2 WHERE id = $1`, v.id, now, p.UserID, clip(note, decisionNoteLimit)); err != nil {
		return 0, fmt.Errorf("activities: approving the visit: %w", err)
	}
	owner, err := fundingOwner(ctx, tx, v.responsible, v.responsible)
	if err != nil {
		return 0, err
	}
	batchID, err := s.dayFor(ctx, tx, v, owner, now)
	if err != nil {
		return 0, err
	}
	if _, err := tx.Exec(ctx, `UPDATE activity SET daily_visit_batch_id = $2 WHERE id = $1`, v.id, batchID); err != nil {
		return 0, fmt.Errorf("activities: putting the visit on its day: %w", err)
	}
	// _price runs with no principal: the costs are the owner's own.
	return keepDayCosts(ctx, tx, [][]string{{batchID, owner}}, owner, auth.Principal{}, now)
}

// clientPoolOpen is the client rule asked at approval: one staff support
// visit a year, the request itself not counted.
func clientPoolOpen(ctx context.Context, q Querier, v *decidedVisit, now time.Time) error {
	if v.universal || v.schoolID == "" || !in(rules.Gate.ClientRuleTypes, v.schoolType) {
		return nil
	}
	if v.purpose == rules.Gate.CompanionPurpose || in(rules.Gate.SSASupportVisitTypes, v.activityType) {
		return nil
	}
	if !in(rules.Gate.InSchoolSupportTypes, v.activityType) && !in(rules.Gate.FollowUpVisitTypes, v.activityType) {
		return nil
	}
	sc, err := schoolByIDOrCode(ctx, q, v.schoolID)
	if err != nil || sc == nil {
		return err
	}
	gate, err := visitgate.Of(ctx, q, schoolprofile.GateRules(),
		visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}, v.fy, schooldirectory.OperationalFY(now))
	if err != nil {
		return fmt.Errorf("activities: reading the school's visit rule: %w", err)
	}
	if !gate.StaffCanSchedule {
		return refuse("%s", gate.StaffReason)
	}
	return nil
}

// dayFor is attach_activity_to_batch: the owner's day for the visit, made if
// they have none.
func (s *Service) dayFor(ctx context.Context, tx pgx.Tx, v *decidedVisit, owner string, now time.Time) (string, error) {
	day := v.planned.Format(time.DateOnly)
	var batchID string
	err := tx.QueryRow(ctx, `SELECT id FROM daily_visit_batch WHERE responsible_user = $1 AND visit_date = $2
ORDER BY created_at LIMIT 1 FOR UPDATE`, owner, day).Scan(&batchID)
	if err == nil {
		return batchID, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("activities: locking the day: %w", err)
	}
	sc, err := schoolByIDOrCode(ctx, tx, v.schoolID)
	if err != nil {
		return "", err
	}
	home, err := staffHomeOf(ctx, tx, v.responsible)
	if err != nil {
		return "", err
	}
	districtType := "primary"
	if sc != nil {
		districtType = districtTypeFor(home, sc.DistrictID, sc.DistrictName, sc.DistrictType)
	}
	batchID = cuid.New()
	if _, err := tx.Exec(ctx, `
INSERT INTO daily_visit_batch (id, created_at, updated_at, responsible_user, visit_date, district_type,
  rate_snapshot, daily_pool_amount, school_count, per_school_amount, workload_snapshot)
VALUES ($1, $2, $2, $3, $4, $5, '{}', 0, 0, 0, '{}')`, batchID, now, owner, day, districtType); err != nil {
		return "", fmt.Errorf("activities: making the day: %w", err)
	}
	return batchID, nil
}

// jsonOf is v as JSON; it is only given plain lists of strings.
func jsonOf(v any) string {
	raw, err := json.Marshal(v)
	if err != nil {
		return "[]"
	}
	return string(raw)
}

// keepDayCosts is costs_follow._hand_over's row for these days.
func keepDayCosts(ctx context.Context, tx pgx.Tx, days [][]string, owner string, p auth.Principal, now time.Time) (int64, error) {
	steps := fmt.Sprintf(`{"days": %s, "together": false, "weeks": [], "months": [], "notes": [], "change": null}`, jsonOf(days))
	var id int64
	err := tx.QueryRow(ctx, `
INSERT INTO daily_visit_costs_to_follow (created_at, updated_at, owners, asked_by, asked_by_role, steps,
  provenance, attempts, held_reason)
VALUES ($1, $1, $2, $3, $4, $5, '{}', 0, '') RETURNING id`,
		now, jsonOf([]string{owner}), p.UserID, p.ActiveRole, steps).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("activities: keeping the costs to follow: %w", err)
	}
	return id, nil
}

// declineInTx is decline's transaction, and _release_core_slot.
func declineInTx(ctx context.Context, tx pgx.Tx, p auth.Principal, v *decidedVisit, reason string, now time.Time) error {
	clipped := clip(reason, decisionNoteLimit)
	if _, err := tx.Exec(ctx, `UPDATE activity SET status = 'rejected', owner_decided_at = $2, owner_decided_by = $3,
  owner_decision_note = $4, last_reason = $4, updated_at = $2 WHERE id = $1`, v.id, now, p.UserID, clipped); err != nil {
		return fmt.Errorf("activities: declining the visit: %w", err)
	}
	if _, err := tx.Exec(ctx, `UPDATE core_activity_slot SET status = 'Planned', activity_id = NULL, scheduled_for = NULL,
  scheduled_month = NULL, scheduled_week = NULL, assigned_staff_id = NULL, assigned_staff_name = NULL,
  owner = 'unassigned', updated_at = $2 WHERE activity_id = $1`, v.id, now); err != nil {
		return fmt.Errorf("activities: handing the package slot back: %w", err)
	}
	return nil
}

// afterDecision is what follows the decision, in the existing order: the
// pricing, the audit row, the owner's notice closed, and the requester told.
// None of it undoes the decision.
func (s *Service) afterDecision(ctx context.Context, p auth.Principal, v *decidedVisit, decision, note string, rowID int64, origin Origin) {
	status := "scheduled"
	action := "visit_request_approve"
	if decision == "decline" {
		status, action = "rejected", "visit_request_decline"
	}
	if rowID != 0 {
		if err := s.pricing.Settle(ctx, []int64{rowID}, v.id); err != nil {
			s.logger.Warn("activities: the approved visit's costs were not settled; the sweep takes them", "activity", v.id, "err", err)
		}
	}
	if err := s.auditDecision(ctx, p, v, action, status, note, origin); err != nil {
		s.logger.Warn("activities: the decision's audit row was not written", "activity", v.id, "err", err)
	}
	if err := s.closeRequestNotice(ctx, v.id); err != nil {
		s.logger.Warn("activities: the owner's request notice was not closed", "activity", v.id, "err", err)
	}
	if v.responsible == "" {
		return
	}
	person := p.Name
	if person == "" {
		person = "A staff member"
	}
	where, on := visitDecisionWhere(v.schoolName), visitDecisionOn(v.planned)
	notice := scheduledNotice{title: "Your visit was approved", event: visitApproved, category: "activity",
		contextType: "Activity", body: fmt.Sprintf("%s approved your visit to %s%s. It is now on your plan.", person, where, on)}
	if decision == "decline" {
		notice = scheduledNotice{title: "Your visit was declined", event: visitDeclined, category: "activity",
			contextType: "Activity", priority: "high",
			body: fmt.Sprintf("%s declined your visit to %s%s: %s", person, where, on, note)}
	}
	sender := workflowNotices{db: s.db, push: s.noticePush, live: s.live, logger: s.logger}
	if err := sender.sendTo(ctx, s.now(), v.id, p.UserID, origin, notice, []noticeRecipient{
		{id: v.responsible, route: visitRequestQueueURL, label: "View Visit Request"},
	}); err != nil {
		s.logger.Warn("activities: the requester was not told", "activity", v.id, "err", err)
	}
}

func (s *Service) closeRequestNotice(ctx context.Context, activityID string) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'Activity', $2, $3)`,
		visitRequestedEvent, activityID, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (s *Service) auditDecision(ctx context.Context, p auth.Principal, v *decidedVisit, action, status, reason string, origin Origin) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(v.id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Reason:    audit.Text(clip(reason, decisionNoteLimit)),
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
		Payload: map[string]any{
			"schoolId": nilIfEmpty(v.schoolID), "activityType": v.activityType, "responsibleStaffId": nilIfEmpty(v.responsible),
			"approvalOwnerId": nilIfEmpty(v.owner), "status": status,
		},
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// auditUnauthorizedDecision is the view's unauthorized_mutation_attempt row.
func (s *Service) auditUnauthorizedDecision(ctx context.Context, p auth.Principal, activityID string, origin Origin) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "unauthorized_mutation_attempt", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(activityID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: false,
		Reason:    audit.Text("Attempted to decide a visit request for a school they do not own."),
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
	}, s.now()); err != nil {
		s.logger.Warn("activities: the unauthorized attempt was not audited", "activity", activityID, "err", err)
		return
	}
	_ = tx.Commit(ctx)
}
