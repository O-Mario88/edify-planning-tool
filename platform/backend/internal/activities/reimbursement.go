package activities

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The officer confirming a disbursed reimbursement arrived
// (my_plan_views.confirm_reimbursement_receipt_action, through
// advance_service.confirm_reimbursement_receipt).

func reimbursementRefusal(answer string) error {
	switch answer {
	case "ok":
		return nil
	case "gone":
		return refuse("%s", "Advance request not found.")
	case "not_owner":
		return refuse("%s", "Only the responsible user can confirm reimbursement receipt.")
	case "nothing":
		return refuse("%s", "Nothing to confirm — no disbursed reimbursement is awaiting receipt confirmation.")
	case "unreconciled":
		return refuse("%s", "Cannot confirm — accounted amount does not reconcile with disbursed minus returned plus reimbursed. Critical finance error.")
	}
	return fmt.Errorf("activities: the reimbursement answered %q", answer)
}

// reimbursementAmount is int(data.get("amount", reimbursed) or 0): nil when
// the drawer sent no amount (the reimbursed amount is kept), nought when it
// sent an empty one.
func reimbursementAmount(raw string, sent bool) (*int64, error) {
	if !sent {
		return nil, nil
	}
	raw = strings.TrimSpace(raw)
	var v int64
	if raw != "" {
		parsed, err := strconv.ParseInt(raw, 10, 64)
		if err != nil {
			return nil, refuse("%s", "Amount received must be a whole UGX number.")
		}
		v = parsed
	}
	return &v, nil
}

// ReimbursementView is what the drawer shows.
type ReimbursementView struct {
	School, Reference string
	Amount            int64
	Waiting           bool
}

// awaitingReimbursement is the view's advance: the latest reimbursed one
// waiting for its receipt.
func (s *Service) awaitingReimbursement(ctx context.Context, p auth.Principal, activityID string) (string, ReimbursementView, error) {
	var delivery, responsible string
	var view ReimbursementView
	err := s.db.QueryRow(ctx, `SELECT COALESCE(a.delivery_type, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(sc.name, '')
  FROM activity a LEFT JOIN school sc ON sc.id = a.school_id WHERE a.id = $1 AND a.deleted_at IS NULL`,
		strings.TrimSpace(activityID)).Scan(&delivery, &responsible, &view.School)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return "", view, refuse("%s", "Not found.")
	case err != nil:
		return "", view, fmt.Errorf("activities: reading the activity: %w", err)
	case p.StaffProfileID == "" || p.InActingAppointment || delivery == "partner" ||
		(responsible != p.StaffProfileID && responsible != p.UserID):
		return "", view, handOn("not the officer's own staff activity")
	}
	var id string
	err = s.db.QueryRow(ctx, `SELECT id, COALESCE(reimbursed_amount, 0)::bigint, COALESCE(reimburse_reference, '')
  FROM advance_request WHERE activity_id = $1 AND status = 'reimbursement_disbursed'
  ORDER BY reimbursed_at DESC NULLS FIRST, created_at DESC LIMIT 1`, activityID).Scan(&id, &view.Amount, &view.Reference)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", view, nil
	}
	if err != nil {
		return "", view, fmt.Errorf("activities: reading the reimbursement: %w", err)
	}
	view.Waiting = true
	return id, view, nil
}

// ReimbursementDrawer reads the drawer for the activity's own officer.
func (s *Service) ReimbursementDrawer(ctx context.Context, p auth.Principal, activityID string) (ReimbursementView, error) {
	_, view, err := s.awaitingReimbursement(ctx, p, activityID)
	return view, err
}

// ConfirmReimbursement saves the drawer; amount is the posted figure, and
// sent whether the drawer posted one.
func (s *Service) ConfirmReimbursement(ctx context.Context, p auth.Principal, activityID, amount string, sent bool, origin Origin) (Answer, error) {
	advanceID, view, err := s.awaitingReimbursement(ctx, p, activityID)
	if err != nil {
		return Answer{}, err
	}
	if !view.Waiting {
		return Answer{}, refuse("%s", "No disbursed reimbursement is awaiting receipt confirmation on this activity.")
	}
	received, err := reimbursementAmount(amount, sent)
	if err != nil {
		return Answer{}, err
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Answer{}, fmt.Errorf("activities: opening the reimbursement: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	if err := tx.QueryRow(ctx, `SELECT gateway_day_money.confirm_reimbursement($1, $2, $3, $4, $5)`,
		advanceID, p.UserID, p.ActiveRole, received, s.now()).Scan(&answer); err != nil {
		return Answer{}, fmt.Errorf("activities: confirming the reimbursement: %w", err)
	}
	if err := reimbursementRefusal(answer); err != nil {
		return Answer{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Answer{}, fmt.Errorf("activities: committing the reimbursement: %w", err)
	}
	confirmed := view.Amount
	if received != nil {
		confirmed = *received
	}
	if err := s.auditAccountability(ctx, p, "advance_request.confirm_reimbursement_receipt", "AdvanceRequest", advanceID,
		map[string]any{"amount": confirmed}, origin); err != nil {
		s.logger.Warn("activities: the reimbursement's audit row was not written", "advance", advanceID, "err", err)
	}
	if err := s.auditAccountability(ctx, p, "reimbursement_receipt_confirmed", "Activity", activityID,
		map[string]any{"advance_id": advanceID, "amount": view.Amount}, origin); err != nil {
		s.logger.Warn("activities: the activity's audit row was not written", "activity", activityID, "err", err)
	}
	return Answer{ActivityID: activityID, Message: savedInPlace}, nil
}
