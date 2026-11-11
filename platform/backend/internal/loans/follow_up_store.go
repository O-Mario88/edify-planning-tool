package loans

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// Staff follow-ups: what a CCEO, PL or other staff member did about a
// school's loan. They are notes, never financial records: a payment the
// school reports is written down for the lender to verify and moves nothing.

// StaffFollowUpRecord is one staff follow-up.
type StaffFollowUpRecord struct {
	ID, ApplicationID, SchoolID, StaffID, StaffName, StaffRole, Method string
	ContactedPerson, Reason, Summary, SchoolFeedback, ReportedIssue    string
	NextAction, EscalationTarget, ResponsibleUserID                    string
	FollowedUpOn                                                       time.Time
	NextFollowUpOn, ReportedPaidOn                                     *time.Time
	PaymentReported                                                    bool
	ReportedAmount                                                     *ledger.Money
	CreatedAt                                                          time.Time
}

// AddStaffFollowUp records a follow-up and, when the school reported a
// payment, says so on the case for the lender to verify.
func (s *Store) AddStaffFollowUp(ctx context.Context, f StaffFollowUpRecord) (string, error) {
	id, err := NewID()
	if err != nil {
		return "", err
	}
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		var partnerID string
		var school *string
		if err := tx.QueryRow(ctx, `SELECT partner_id, school_id FROM school_loans.application WHERE id = $1 FOR UPDATE`,
			f.ApplicationID).Scan(&partnerID, &school); errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		} else if err != nil {
			return err
		}
		var amount *string
		if f.ReportedAmount != nil {
			text := f.ReportedAmount.String()
			amount = &text
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.follow_up (id, application_id, staff_id, staff_name, staff_active_role, followed_up_on, channel,
  lender_partner_id, notes, next_action, next_follow_up_on, school_id, contacted_person, reason, school_feedback,
  reported_issue, escalation_target, responsible_user_id, payment_reported, reported_amount, reported_paid_on, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20::numeric, $21, $22)`,
			id, f.ApplicationID, f.StaffID, f.StaffName, f.StaffRole, f.FollowedUpOn, f.Method, partnerID, f.Summary,
			f.NextAction, f.NextFollowUpOn, school, f.ContactedPerson, f.Reason, f.SchoolFeedback, f.ReportedIssue,
			f.EscalationTarget, f.ResponsibleUserID, f.PaymentReported, amount, f.ReportedPaidOn, f.CreatedAt); err != nil {
			return fmt.Errorf("loans: storing a staff follow-up: %w", err)
		}
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.application
SET last_follow_up_at = $2, next_follow_up_on = COALESCE($3, next_follow_up_on), updated_at = $2 WHERE id = $1`,
			f.ApplicationID, f.CreatedAt, f.NextFollowUpOn); err != nil {
			return err
		}
		note := "Followed up (" + followUpReasonLabel(f.Reason) + ") by " + f.Method + "."
		if err := appendEvent(ctx, tx, Event{ApplicationID: f.ApplicationID, Kind: "follow_up", ActorKind: "staff",
			ActorID: f.StaffID, ActorName: f.StaffName, Note: note}); err != nil {
			return err
		}
		if !f.PaymentReported {
			return nil
		}
		paid := "a payment"
		if f.ReportedAmount != nil {
			paid = "a payment of " + ugx(*f.ReportedAmount)
		}
		if f.ReportedPaidOn != nil {
			paid += " on " + day(*f.ReportedPaidOn)
		}
		return appendEvent(ctx, tx, Event{ApplicationID: f.ApplicationID, Kind: "payment_reported", ActorKind: "staff",
			ActorID: f.StaffID, ActorName: f.StaffName,
			Note: "The school told Edify it made " + paid + ". Awaiting the lender's verification; the balance is unchanged."})
	})
	return id, err
}

// StaffFollowUps are an application's follow-ups, newest first.
func (s *Store) StaffFollowUps(ctx context.Context, applicationID string) ([]StaffFollowUpRecord, error) {
	rows, err := s.db.Query(ctx, `
SELECT id::text, staff_id, staff_name, staff_active_role, channel, contacted_person, reason, notes, school_feedback,
  reported_issue, next_action, escalation_target, followed_up_on, next_follow_up_on, payment_reported,
  reported_amount::text, reported_paid_on, created_at
FROM school_loans.follow_up WHERE application_id = $1 AND NOT is_oversight ORDER BY created_at DESC LIMIT 100`, applicationID)
	if err != nil {
		return nil, fmt.Errorf("loans: reading staff follow-ups: %w", err)
	}
	defer rows.Close()
	var out []StaffFollowUpRecord
	for rows.Next() {
		var f StaffFollowUpRecord
		var amount *string
		if err := rows.Scan(&f.ID, &f.StaffID, &f.StaffName, &f.StaffRole, &f.Method, &f.ContactedPerson, &f.Reason, &f.Summary,
			&f.SchoolFeedback, &f.ReportedIssue, &f.NextAction, &f.EscalationTarget, &f.FollowedUpOn, &f.NextFollowUpOn,
			&f.PaymentReported, &amount, &f.ReportedPaidOn, &f.CreatedAt); err != nil {
			return nil, err
		}
		if amount != nil {
			m := money(amount)
			f.ReportedAmount = &m
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

// NextFollowUp is the application's next follow-up date, if any.
func (s *Store) NextFollowUp(ctx context.Context, applicationID string) (*time.Time, error) {
	var next *time.Time
	err := s.db.QueryRow(ctx, `SELECT next_follow_up_on FROM school_loans.application WHERE id = $1`, applicationID).Scan(&next)
	return next, err
}

// LastNotification is the newest notification's label and time, if any.
func (s *Store) LastNotification(ctx context.Context, applicationID string) (string, error) {
	var kind, status string
	var at time.Time
	err := s.db.QueryRow(ctx, `
SELECT type, status, created_at FROM school_loans.notification WHERE application_id = $1 ORDER BY created_at DESC LIMIT 1`,
		applicationID).Scan(&kind, &status, &at)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return NoteLabels[kind] + " · " + at.In(kampala).Format("2 Jan") + " · " + deliveryStatusLabels[status], nil
}

// ChangeCursor is when anything about school loans last changed.
func (s *Store) ChangeCursor(ctx context.Context) (time.Time, error) {
	var at *time.Time
	err := s.db.QueryRow(ctx, `
SELECT GREATEST((SELECT max(created_at) FROM school_loans.application_event),
                (SELECT max(updated_at) FROM school_loans.notification))`).Scan(&at)
	if err != nil || at == nil {
		return time.Time{}, err
	}
	return *at, nil
}

// Follow-up reasons and methods.
var (
	followUpReasons = []Option{{"not_acknowledged", "Application not acknowledged"}, {"assessment_delayed", "Assessment delayed"},
		{"documents_required", "Additional documents required"}, {"decision_pending", "Loan decision pending"},
		{"disbursement_delayed", "Disbursement delayed"}, {"installment_approaching", "Installment approaching"},
		{"repayment_overdue", "Repayment overdue"}, {"payment_discrepancy", "Payment discrepancy"},
		{"collateral_delayed", "Collateral release delayed"}, {"other", "Other"}}
	followUpMethods = []Option{{"phone", "Phone call"}, {"visit", "School visit"}, {"sms", "SMS"}, {"whatsapp", "WhatsApp"},
		{"email", "Email"}, {"meeting", "Meeting"}, {"other", "Other"}}
)

func followUpReasonLabel(reason string) string { return labelOf(followUpReasons, reason) }

// LenderContact is the lender's confirmed receiving address, for Edify staff
// to contact the lender through its official channel.
func (s *Store) LenderContact(ctx context.Context, partnerID string) (string, error) {
	var email string
	err := s.db.QueryRow(ctx, `
SELECT COALESCE(confirmed_email, '') FROM school_loans.lender_channel WHERE partner_id = $1 AND confirmed_at IS NOT NULL`,
		partnerID).Scan(&email)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	return email, err
}
