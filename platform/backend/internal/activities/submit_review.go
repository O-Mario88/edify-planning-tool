package activities

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// Submit for review (my_plan_views.submit_for_review_action and
// services.submit_for_review) for an officer's own staff school visit: work
// started, or returned by its reviewer, handed in again with its Salesforce
// ID to the officer's Programme Lead.

// submittableStatuses are services.SUBMITTABLE_STATUSES.
var submittableStatuses = []string{
	"completion_started", "in_progress", "evidence_uploaded", "evidence_accepted", "salesforce_id_required",
	"returned", "returned_by_pl", "returned_by_ia", "completed",
}

const (
	notSubmittable = "Activity is not ready to be submitted for review."
	submitNeedsID  = "Enter the Salesforce Activity ID before submitting."
)

// submitRefusal is submit_for_review's first two refusals, in its order.
func submitRefusal(status, salesforceID string) string {
	switch {
	case !slices.Contains(submittableStatuses, status):
		return notSubmittable
	case salesforceID == "":
		return submitNeedsID
	}
	return ""
}

// submitAnswer reads gateway_completion.submit_for_review's answer.
func submitAnswer(answer string) error {
	switch answer {
	case "":
		return nil
	case "not_ready":
		return refuse(notSubmittable)
	case "no_id":
		return refuse(submitNeedsID)
	}
	return handOn("the submission met " + answer)
}

// SubmitForReview hands the visit in, or refuses it in the existing words, or
// hands it on (ErrHandOn).
func (s *Service) SubmitForReview(ctx context.Context, p auth.Principal, activityID string, origin Origin) (Answer, error) {
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return Answer{}, handOn("not an officer submitting their own visit")
	}
	a, err := readCompletedVisit(ctx, s.db, strings.TrimSpace(activityID))
	if err != nil {
		return Answer{}, err
	}
	switch {
	case a == nil:
		return Answer{}, handOn("not a staff school visit with a school and a day")
	case a.other:
		return Answer{}, handOn("a visit in a cluster, a project, a pair or a partner's hands, or a OneTest visit")
	case a.responsible != p.StaffProfileID:
		return Answer{}, handOn("someone else's visit")
	}
	now := s.now()
	if err := s.ownVisitSchool(ctx, p, a.schoolID, now); err != nil {
		return Answer{}, err
	}
	switch {
	case in(completionPurposes, a.purpose) || a.collectsSSA:
		return Answer{}, handOn("a visit whose purpose binds a training or collects the SSA")
	case a.verification == confirmedVerification:
		return Answer{}, handOn("a visit IA has confirmed")
	case !in(visitRecordTypes, strings.ToUpper(a.recordType)) || a.costing == onetestCostingProfile:
		return Answer{}, handOn("a visit kept under another Salesforce record type, or a OneTest visit")
	}
	if refusal := submitRefusal(a.status, a.salesforceID); refusal != "" {
		return Answer{}, refuse("%s", refusal)
	}
	moved, err := doneOnAnotherDay(ctx, s.db, a)
	if err != nil {
		return Answer{}, err
	}
	if moved {
		return Answer{}, handOn("done on another day than planned: the work and its money move")
	}
	if err := s.writeSubmission(ctx, p, a.id, now); err != nil {
		return Answer{}, err
	}
	if follower, ok := s.pricing.(CompletionFollower); ok {
		if err := follower.HandedIn(ctx, a.id, p.UserID, p.ActiveRole); err != nil {
			s.logger.Warn("activities: the hand-in's notices were not sent", "activity", a.id, "err", err)
		}
	}
	if err := s.auditSubmitted(ctx, p, a.id, origin); err != nil {
		s.logger.Warn("activities: the submission's audit row was not written", "activity", a.id, "err", err)
	}
	if in(rules.LedgerCreditedTypes, a.activityType) {
		if err := s.markOwnerYears(ctx, a.responsible, a.plannedDate); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", a.id, "err", err)
		}
	}
	return Answer{ActivityID: a.id, Status: handedInStatus, Message: rules.Move.SavedMessage}, nil
}

// doneOnAnotherDay is move_to_completed_day's question: a delivery day
// recorded apart from the planned day moves the work and its money.
func doneOnAnotherDay(ctx context.Context, q Querier, a *completedVisit) (bool, error) {
	var delivered *time.Time
	err := q.QueryRow(ctx, `SELECT actual_delivery_date FROM activity WHERE id = $1`, a.id).Scan(&delivered)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("activities: reading the delivery day: %w", err)
	}
	return delivered != nil && !sameDay(*delivered, a.plannedDate), nil
}

// writeSubmission is submit_for_review's transaction, through the narrow
// function the gateway may ask.
func (s *Service) writeSubmission(ctx context.Context, p auth.Principal, activityID string, now time.Time) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the submission: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	if err := tx.QueryRow(ctx, `SELECT gateway_completion.submit_for_review($1, $2, $3, $4)`,
		activityID, p.UserID, now, cuid.New()).Scan(&answer); err != nil {
		return fmt.Errorf("activities: submitting the visit: %w", err)
	}
	if err := submitAnswer(answer); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the submission: %w", err)
	}
	return nil
}

func (s *Service) auditSubmitted(ctx context.Context, p auth.Principal, activityID string, origin Origin) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, p.UserID, s.now())
	if err != nil {
		return err
	}
	var data any
	if stamped := withStamps(nil, cover); len(stamped) > 0 {
		data = stamped
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "submit_for_review", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(activityID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Reason:    audit.Text("Activity submitted for PL/IA review"),
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
		Payload: data,
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
