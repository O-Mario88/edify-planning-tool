package loans

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Actor is whoever moves an application on.
type Actor struct {
	Kind      string // ActorLender, ActorStaff, ActorStaffCorrection
	ID        string // a user id, or a lender session's verified address
	Name      string
	PartnerID string // a lender: the only lender whose applications it may touch
}

// ActDetails are what an action records beside the new status.
type ActDetails struct {
	Note                  string
	Evidence              string
	ApprovedAmount        int64
	DisbursedAmount       int64
	DisbursementDate      time.Time
	DisbursementReference string
	TermMonths            int
	InterestRate          string
}

// FieldError is a detail an action needs and did not get.
type FieldError struct {
	Field   string
	Message string
}

func (e *FieldError) Error() string { return e.Message }

func need(field, message string) error { return &FieldError{Field: field, Message: message} }

// checkDetails holds the brief's rules on what each action must carry:
// approved, disbursed and requested amounts are separate and never assumed
// equal; a disbursement needs its date and evidence; a decision recorded by
// staff needs the lender's evidence.
func checkDetails(action string, actor Actor, details ActDetails, submitted, today time.Time) error {
	if actor.Kind == ActorStaffCorrection {
		if strings.TrimSpace(details.Evidence) == "" {
			return need("evidence", "Name the lender's evidence (a letter, an email, a loan reference) for this correction.")
		}
		if strings.TrimSpace(details.Note) == "" {
			return need("note", "Say why staff are recording this instead of the lender.")
		}
	}
	switch action {
	case ActionRequestInformation:
		if strings.TrimSpace(details.Note) == "" {
			return need("note", "Say what information is needed.")
		}
	case ActionDecline:
		if strings.TrimSpace(details.Note) == "" {
			return need("note", "Give the reason for declining.")
		}
	case ActionApprove:
		if details.ApprovedAmount <= 0 {
			return need("approved_amount", "Enter the approved amount in UGX.")
		}
	case ActionDisburse:
		switch {
		case details.DisbursedAmount <= 0:
			return need("disbursed_amount", "Enter the amount actually disbursed in UGX.")
		case details.DisbursementDate.IsZero():
			return need("disbursement_date", "Enter the date the money was disbursed.")
		case details.DisbursementDate.After(today):
			return need("disbursement_date", "A disbursement date cannot be in the future.")
		case details.DisbursementDate.Before(dayOf(submitted)):
			return need("disbursement_date", "A disbursement cannot be dated before the application was submitted.")
		case strings.TrimSpace(details.DisbursementReference) == "":
			return need("disbursement_reference", "Enter the loan or transaction reference for this disbursement.")
		}
	case ActionWithdraw, ActionClose:
		if strings.TrimSpace(details.Note) == "" {
			return need("note", "Add a note saying why.")
		}
	}
	if details.TermMonths < 0 || details.TermMonths > 240 {
		return need("term_months", "Enter a term from 1 to 240 months.")
	}
	if len(details.InterestRate) > 120 || len(details.Note) > 4000 || len(details.Evidence) > 500 ||
		len(details.DisbursementReference) > 200 {
		return need("note", "Keep the text shorter.")
	}
	return nil
}

func dayOf(at time.Time) time.Time {
	local := at.In(kampala)
	return time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, kampala)
}

var actionEvents = map[string]string{
	ActionAcknowledge:        "lender_acknowledged",
	ActionStartReview:        "status_changed",
	ActionRequestInformation: "information_requested",
	ActionApprove:            "approved",
	ActionDecline:            "declined",
	ActionDisburse:           "disbursed",
	ActionClose:              "closed",
	ActionWithdraw:           "withdrawn",
}

// Act moves an application on, after checking who may, from where, and with
// what. A lender reaches only its own applications; anything else is
// ErrNotFound, never a hint that the application exists.
func (s *Store) Act(ctx context.Context, applicationID string, actor Actor, action string, details ActDetails, now time.Time) (string, error) {
	var to string
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		var status, partnerID string
		var submitted time.Time
		err := tx.QueryRow(ctx, `
SELECT status, partner_id, submitted_at FROM school_loans.application WHERE id = $1 FOR UPDATE`, applicationID).
			Scan(&status, &partnerID, &submitted)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		if actor.Kind == ActorLender && partnerID != actor.PartnerID {
			return ErrNotFound
		}
		if to, err = NextStatus(status, action, actor.Kind); err != nil {
			return &FieldError{Field: "action", Message: capitalise(err.Error()) + "."}
		}
		if err := checkDetails(action, actor, details, submitted, dayOf(now)); err != nil {
			return err
		}
		var term *int
		if details.TermMonths > 0 {
			term = &details.TermMonths
		}
		_, err = tx.Exec(ctx, `
UPDATE school_loans.application SET
  status = $2,
  lender_received_at = CASE WHEN $3 AND lender_received_at IS NULL THEN $4 ELSE lender_received_at END,
  delivery_status = CASE WHEN $5 THEN 'opened_by_lender' ELSE delivery_status END,
  decided_at = CASE WHEN $2 IN ('approved', 'declined') THEN $4 ELSE decided_at END,
  approved_amount_ugx = CASE WHEN $2 = 'approved' THEN $6 ELSE approved_amount_ugx END,
  disbursed_amount_ugx = CASE WHEN $2 = 'disbursed' THEN $7 ELSE disbursed_amount_ugx END,
  disbursement_date = CASE WHEN $2 = 'disbursed' THEN $8 ELSE disbursement_date END,
  disbursement_reference = CASE WHEN $2 = 'disbursed' THEN $9 ELSE disbursement_reference END,
  agreed_term_months = COALESCE($10, agreed_term_months),
  interest_rate_text = CASE WHEN $11 <> '' THEN $11 ELSE interest_rate_text END,
  next_follow_up_on = CASE WHEN $2 IN ('declined', 'disbursed', 'closed', 'withdrawn') THEN NULL ELSE next_follow_up_on END,
  updated_at = $4
WHERE id = $1`,
			applicationID, to, lenderTouches(status, to), now, actor.Kind == ActorLender,
			nullableAmount(details.ApprovedAmount), nullableAmount(details.DisbursedAmount),
			nullableDate(details.DisbursementDate), strings.TrimSpace(details.DisbursementReference),
			term, strings.TrimSpace(details.InterestRate))
		if err != nil {
			return fmt.Errorf("loans: recording %s: %w", action, err)
		}
		note := strings.TrimSpace(details.Note)
		if summary := detailSummary(action, details); summary != "" {
			note = strings.TrimSpace(summary + " " + note)
		}
		eventActor := actor.Kind
		if eventActor == ActorStaffCorrection {
			eventActor = "staff"
			note = "Recorded by Edify staff for the lender (correction). " + note
		}
		return appendEvent(ctx, tx, Event{
			ApplicationID: applicationID, Kind: actionEvents[action], ActorKind: eventActor,
			ActorID: actor.ID, ActorName: actor.Name, FromStatus: status, ToStatus: to,
			Note: note, Evidence: strings.TrimSpace(details.Evidence),
		})
	})
	return to, err
}

// lenderTouches: anything the lender records after the application reached
// it means it was received.
func lenderTouches(from, to string) bool {
	return to != StatusWithdrawn && to != StatusClosed && (from == StatusSubmitted || from == StatusAwaitingReceipt || to == StatusReceived)
}

func detailSummary(action string, details ActDetails) string {
	switch action {
	case ActionApprove:
		summary := "Approved " + FormatUGX(details.ApprovedAmount) + "."
		if details.TermMonths > 0 {
			summary += fmt.Sprintf(" Term %d months.", details.TermMonths)
		}
		return summary
	case ActionDisburse:
		return "Disbursed " + FormatUGX(details.DisbursedAmount) + " on " +
			details.DisbursementDate.Format("2 January 2006") + ", reference " + details.DisbursementReference + "."
	}
	return ""
}

func nullableAmount(value int64) *int64 {
	if value <= 0 {
		return nil
	}
	return &value
}

func nullableDate(value time.Time) *time.Time {
	if value.IsZero() {
		return nil
	}
	return &value
}

func capitalise(text string) string {
	if text == "" {
		return text
	}
	return strings.ToUpper(text[:1]) + text[1:]
}

// MarkOpened records that the lender opened an application it was sent.
func (s *Store) MarkOpened(ctx context.Context, applicationID string, actor Actor, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.application SET delivery_status = 'opened_by_lender', updated_at = $3
WHERE id = $1 AND partner_id = $2 AND delivery_status <> 'opened_by_lender'`, applicationID, actor.PartnerID, now)
		if err != nil || tag.RowsAffected() == 0 {
			return err
		}
		return appendEvent(ctx, tx, Event{
			ApplicationID: applicationID, Kind: "lender_opened", ActorKind: "lender",
			ActorID: actor.ID, ActorName: actor.Name, Note: "The lender opened the application.",
		})
	})
}

// LenderMessage records a lender's message to Edify staff.
func (s *Store) LenderMessage(ctx context.Context, applicationID string, actor Actor, text string) error {
	text = strings.TrimSpace(text)
	if text == "" || len(text) > 4000 {
		return need("message", "Write a message of up to 4,000 characters.")
	}
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var partnerID string
		err := tx.QueryRow(ctx, `SELECT partner_id FROM school_loans.application WHERE id = $1`, applicationID).Scan(&partnerID)
		if errors.Is(err, pgx.ErrNoRows) || (err == nil && partnerID != actor.PartnerID) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{
			ApplicationID: applicationID, Kind: "lender_message", ActorKind: "lender",
			ActorID: actor.ID, ActorName: actor.Name, Note: text,
		})
	})
}
