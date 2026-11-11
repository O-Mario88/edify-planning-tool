package loans

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// Option is something a person may choose in an action's field.
type Option struct{ Value, Label string }

func options(ctx context.Context, s *Store, sql string, args ...any) ([]Option, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("loans: reading choices: %w", err)
	}
	defer rows.Close()
	var out []Option
	for rows.Next() {
		var o Option
		if err := rows.Scan(&o.Value, &o.Label); err != nil {
			return nil, err
		}
		out = append(out, o)
	}
	return out, rows.Err()
}

// OpenCases are a school's open Business Transformation cases: a referral
// to the ledger is made under one of them (the existing workflow's rule).
func (s *Store) OpenCases(ctx context.Context, schoolID string) ([]Option, error) {
	return options(ctx, s, `
SELECT id, 'Case ' || id || ' (' || status || ')' FROM bt_case
WHERE school_id = $1 AND deleted_at IS NULL AND closed_at IS NULL ORDER BY id`, schoolID)
}

// GovernedPurposes are the existing workflow's active loan purposes.
func (s *Store) GovernedPurposes(ctx context.Context) ([]Option, error) {
	return options(ctx, s, `SELECT id, label FROM bt_loan_purpose WHERE active ORDER BY label`)
}

// Facilities are a lender's approved funding facilities.
func (s *Store) Facilities(ctx context.Context, mfiID string) ([]Option, error) {
	return options(ctx, s, `
SELECT id, name || ' (' || currency || ', ' || status || ')' FROM bt_funding_facility
WHERE mfi_id = $1 AND status IN ('approved', 'active') ORDER BY name`, mfiID)
}

// HasFacilityAllocation says whether a ledger loan has a reserved allocation.
func (s *Store) HasFacilityAllocation(ctx context.Context, loanID string) (bool, error) {
	var found bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM bt_funding_facility_allocation WHERE loan_id = $1 AND status <> 'released')`, loanID).Scan(&found)
	return found, err
}

// MFIOfPartner is the lender record of a Loan Partner.
func (s *Store) MFIOfPartner(ctx context.Context, partnerID string) (string, error) {
	var mfi string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(loan_lender_id, '') FROM partner WHERE id = $1`, partnerID).Scan(&mfi)
	return mfi, err
}

// PhoneVerified says whether the director's phone for an application was
// confirmed: a code sent to it was entered, or an officer recorded reaching
// the school on it.
func (s *Store) PhoneVerified(ctx context.Context, applicationID string) (bool, error) {
	var verified bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM school_loans.school_verification v JOIN school_loans.school_access a ON a.id = v.access_id
  WHERE a.application_id = $1 AND a.channel = 'sms' AND v.verified_at IS NOT NULL)
OR EXISTS (
  SELECT 1 FROM school_loans.contact_log c
  WHERE c.application_id = $1 AND c.method IN ('phone', 'sms', 'whatsapp') AND c.outcome IN ('reached', 'visit_scheduled'))`,
		applicationID).Scan(&verified)
	return verified, err
}

// ConsentRecordedAt is when the applicant consented to sharing their
// application, which the existing ledger's referral records.
func (s *Store) ConsentRecordedAt(ctx context.Context, applicationID string) (time.Time, error) {
	var at time.Time
	err := s.db.QueryRow(ctx, `SELECT consent_recorded_at FROM school_loans.application WHERE id = $1`, applicationID).Scan(&at)
	if errors.Is(err, pgx.ErrNoRows) {
		return at, ErrNotFound
	}
	return at, err
}

// CaseIDs are the applications a viewer may work, newest first: a lender's
// (partnerID), or one officer's open assignments (officerID), or every
// application addressed to a lender when both are empty.
func (s *Store) CaseIDs(ctx context.Context, partnerID, officerID string, limit int) ([]string, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id::text FROM school_loans.application a
WHERE a.partner_id IS NOT NULL AND ($1 = '' OR a.partner_id = $1)
  AND ($2 = '' OR EXISTS (SELECT 1 FROM school_loans.assignment x
       WHERE x.application_id = a.id AND x.officer_user_id = $2 AND x.ended_at IS NULL))
ORDER BY a.submitted_at DESC LIMIT $3`, partnerID, officerID, limit)
	if err != nil {
		return nil, fmt.Errorf("loans: listing cases: %w", err)
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}

// DisbursementReadiness is what the existing ledger requires before a
// loan's first disbursement: its purpose plan's total and whether an
// enrolment baseline is recorded.
func (s *Store) DisbursementReadiness(ctx context.Context, loanID string) (planned string, baseline bool, err error) {
	err = s.db.QueryRow(ctx, `
SELECT COALESCE((SELECT sum(planned_amount) FROM bt_loan_purpose_allocation WHERE loan_id = $1), 0)::text,
  EXISTS (SELECT 1 FROM bt_enrolment_snapshot WHERE loan_id = $1 AND kind = 'baseline')`, loanID).Scan(&planned, &baseline)
	if err != nil {
		return "", false, fmt.Errorf("loans: reading disbursement readiness: %w", err)
	}
	return planned, baseline, nil
}
