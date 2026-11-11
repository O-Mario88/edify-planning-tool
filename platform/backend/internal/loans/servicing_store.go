package loans

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// LedgerLoan is a loan as the existing ledger holds it.
type LedgerLoan struct {
	ID, MFIID, SchoolID, ReferralID, FacilityID, ExternalReference, OfficerReference, Status string
	Requested, Approved                                                                      ledger.Money
	TermMonths                                                                               int
}

func money(raw *string) ledger.Money {
	if raw == nil {
		return 0
	}
	m, err := ledger.ParseMoney(*raw)
	if err != nil {
		return 0
	}
	return m
}

// LedgerBook reads one loan's postings from the existing ledger into the
// engine's Book: disbursements (with reversals), the latest schedule
// version, and repayment transactions with their allocations. Penalty
// allocations, which the platform never makes, are left out of the Book and
// returned as penaltyPaid so nothing is hidden.
func (s *Store) LedgerBook(ctx context.Context, loanID string) (LedgerLoan, ledger.Book, ledger.Money, error) {
	var loan LedgerLoan
	var requested, approved *string
	var term *int
	err := s.db.QueryRow(ctx, `
SELECT id, mfi_id, school_id, COALESCE(referral_id, ''), COALESCE(facility_id, ''), external_loan_reference,
  COALESCE(assigned_officer_reference, ''), status, requested_amount::text, approved_amount::text, term_months
FROM bt_mfi_loan WHERE id = $1 AND deleted_at IS NULL`, loanID).Scan(&loan.ID, &loan.MFIID, &loan.SchoolID,
		&loan.ReferralID, &loan.FacilityID, &loan.ExternalReference, &loan.OfficerReference, &loan.Status,
		&requested, &approved, &term)
	if errors.Is(err, pgx.ErrNoRows) {
		return loan, ledger.Book{}, 0, ErrNotFound
	}
	if err != nil {
		return loan, ledger.Book{}, 0, fmt.Errorf("loans: reading a ledger loan: %w", err)
	}
	loan.Requested, loan.Approved = money(requested), money(approved)
	if term != nil {
		loan.TermMonths = *term
	}
	var book ledger.Book

	rows, err := s.db.Query(ctx, `
SELECT d.id, d.amount::text, d.value_date, d.external_reference, r.reversed_at
FROM bt_loan_disbursement d LEFT JOIN bt_loan_disbursement_reversal r ON r.disbursement_id = d.id
WHERE d.loan_id = $1 ORDER BY d.value_date, d.sequence`, loanID)
	if err != nil {
		return loan, book, 0, fmt.Errorf("loans: reading disbursements: %w", err)
	}
	for rows.Next() {
		var d ledger.Disbursement
		var amount string
		var reversed *time.Time
		if err := rows.Scan(&d.ID, &amount, &d.ValueDate, &d.Reference, &reversed); err != nil {
			rows.Close()
			return loan, book, 0, err
		}
		d.Amount = money(&amount)
		if reversed != nil {
			day := ledger.DayOf(reversed.In(kampala))
			d.ReversedOn = &day
		}
		book.Disbursements = append(book.Disbursements, d)
	}
	rows.Close()

	if err := s.db.QueryRow(ctx, `SELECT COALESCE(max(schedule_version), 0) FROM bt_loan_repayment_installment WHERE loan_id = $1`,
		loanID).Scan(&book.ScheduleVersion); err != nil {
		return loan, book, 0, err
	}
	rows, err = s.db.Query(ctx, `
SELECT id, installment_number, due_date, principal_due::text, interest_due::text, fee_due::text
FROM bt_loan_repayment_installment WHERE loan_id = $1 AND schedule_version = $2 ORDER BY due_date, installment_number`,
		loanID, book.ScheduleVersion)
	if err != nil {
		return loan, book, 0, fmt.Errorf("loans: reading the schedule: %w", err)
	}
	for rows.Next() {
		var i ledger.Installment
		var principal, interest, fee string
		if err := rows.Scan(&i.ID, &i.Number, &i.DueDate, &principal, &interest, &fee); err != nil {
			rows.Close()
			return loan, book, 0, err
		}
		i.Principal, i.Interest, i.Fee = money(&principal), money(&interest), money(&fee)
		i.DueDate = ledger.DayOf(i.DueDate)
		book.Installments = append(book.Installments, i)
	}
	rows.Close()
	opening := book.NetDisbursed(time.Date(9999, 1, 1, 0, 0, 0, 0, time.UTC))
	for index := range book.Installments {
		book.Installments[index].OpeningBalance = opening
		opening -= book.Installments[index].Principal
	}

	rows, err = s.db.Query(ctx, `
SELECT t.id, t.kind, COALESCE(t.reversal_of_id, ''), t.amount::text, t.value_date, t.external_reference,
  a.installment_id, a.component, a.amount::text
FROM bt_repayment_transaction t LEFT JOIN bt_repayment_allocation a ON a.transaction_id = t.id
WHERE t.loan_id = $1 ORDER BY t.value_date, t.posted_at, t.id`, loanID)
	if err != nil {
		return loan, book, 0, fmt.Errorf("loans: reading repayments: %w", err)
	}
	defer rows.Close()
	var penaltyPaid ledger.Money
	index := map[string]int{}
	for rows.Next() {
		var p ledger.Payment
		var amount string
		var installment, component, allocated *string
		if err := rows.Scan(&p.ID, &p.Kind, &p.ReversalOf, &amount, &p.ValueDate, &p.Reference,
			&installment, &component, &allocated); err != nil {
			return loan, book, 0, err
		}
		at, seen := index[p.ID]
		if !seen {
			p.Amount = money(&amount)
			p.ValueDate = ledger.DayOf(p.ValueDate)
			book.Payments = append(book.Payments, p)
			at = len(book.Payments) - 1
			index[p.ID] = at
		}
		if installment == nil || component == nil {
			continue
		}
		if *component == "penalty" {
			if book.Payments[at].Kind == ledger.KindReversal {
				penaltyPaid -= money(allocated)
			} else {
				penaltyPaid += money(allocated)
			}
			continue
		}
		book.Payments[at].Allocations = append(book.Payments[at].Allocations, ledger.Allocation{
			InstallmentID: *installment, Component: ledger.Component(*component), Amount: money(allocated),
		})
	}
	return loan, book, penaltyPaid, rows.Err()
}

// LenderIdentity is who a lender's staff member is in the platform.
type LenderIdentity struct {
	PartnerID, MFIID, LenderName, UserID, Name, OfficerReference string
	Roles                                                        map[string]bool
}

// Lender operational roles (school_loans.lender_member.roles).
const (
	RoleAdministrator  = "administrator"
	RoleLoanOfficer    = "loan_officer"
	RoleCreditApprover = "credit_approver"
	RoleFinance        = "finance_officer"
	RoleCollections    = "collections_officer"
)

// LenderRoleLabels name the roles for people.
var LenderRoleLabels = map[string]string{
	RoleAdministrator: "Lending Partner Administrator", RoleLoanOfficer: "Loan Officer",
	RoleCreditApprover: "Credit Approver", RoleFinance: "Disbursement / Finance Officer",
	RoleCollections: "Collections / Repayment Officer",
}

// Has says whether the member holds a role.
func (l LenderIdentity) Has(role string) bool { return l.Roles[role] }

// ErrNotLenderStaff: the account is not an active member of a Loan Partner,
// or its access to the platform was switched off.
var ErrNotLenderStaff = errors.New("loans: not an active member of a lending partner")

// LenderIdentityOf resolves a lender's staff member: their active
// membership of a lender (bt_mfi_membership, the existing team record), the
// Loan Partner that lender is, and the duties the lender's administrator
// gave them. An MFI Partner Administrator is an administrator; a member
// with no roles recorded yet is a loan officer. A member switched off here
// has no access, whatever their membership says.
func (s *Store) LenderIdentityOf(ctx context.Context, userID, accountRole, name string) (LenderIdentity, error) {
	identity := LenderIdentity{UserID: userID, Name: name, Roles: map[string]bool{}}
	err := s.db.QueryRow(ctx, `
SELECT p.id, m.id, p.name, COALESCE(mm.officer_reference, '')
FROM bt_mfi_membership mm
JOIN bt_mfi_organization m ON m.id = mm.mfi_id AND m.deleted_at IS NULL
JOIN partner p ON p.loan_lender_id = m.id AND p.deleted_at IS NULL AND p.partner_role = 'loan'
WHERE mm.user_id = $1 AND mm.active ORDER BY p.name LIMIT 1`, userID).
		Scan(&identity.PartnerID, &identity.MFIID, &identity.LenderName, &identity.OfficerReference)
	if errors.Is(err, pgx.ErrNoRows) {
		return identity, ErrNotLenderStaff
	}
	if err != nil {
		return identity, fmt.Errorf("loans: reading a lender membership: %w", err)
	}
	var roles []string
	var active bool
	err = s.db.QueryRow(ctx, `SELECT roles, active FROM school_loans.lender_member WHERE partner_id = $1 AND user_id = $2`,
		identity.PartnerID, userID).Scan(&roles, &active)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		if accountRole == roleMFIAdmin {
			roles = []string{RoleAdministrator}
		} else {
			roles = []string{RoleLoanOfficer}
		}
	case err != nil:
		return identity, fmt.Errorf("loans: reading lender roles: %w", err)
	case !active:
		return identity, ErrNotLenderStaff
	}
	for _, role := range roles {
		identity.Roles[role] = true
	}
	if accountRole == roleMFIAdmin {
		identity.Roles[RoleAdministrator] = true
	}
	return identity, nil
}

// TeamMember is one person of a lender's team.
type TeamMember struct {
	UserID, Name, Email, AccountRole, OfficerReference string
	MembershipActive, PlatformActive                   bool
	Roles                                              []string
	OpenCases                                          int
}

// Team is a lender's people: everyone with a membership of its lender, with
// their platform roles and open case load.
func (s *Store) Team(ctx context.Context, partnerID string) ([]TeamMember, error) {
	rows, err := s.db.Query(ctx, `
SELECT u.id, u.name, u.email, COALESCE(u.active_role, ''), COALESCE(mm.officer_reference, ''), mm.active,
  COALESCE(lm.active, true), COALESCE(lm.roles, '{}'),
  (SELECT count(*) FROM school_loans.assignment a JOIN school_loans.application ap ON ap.id = a.application_id
   WHERE a.officer_user_id = u.id AND a.ended_at IS NULL AND ap.partner_id = p.id AND ap.closure_status <> 'closed')
FROM partner p
JOIN bt_mfi_membership mm ON mm.mfi_id = p.loan_lender_id
JOIN "user" u ON u.id = mm.user_id AND u.deleted_at IS NULL
LEFT JOIN school_loans.lender_member lm ON lm.partner_id = p.id AND lm.user_id = u.id
WHERE p.id = $1 ORDER BY u.name`, partnerID)
	if err != nil {
		return nil, fmt.Errorf("loans: reading a lender team: %w", err)
	}
	defer rows.Close()
	var team []TeamMember
	for rows.Next() {
		var m TeamMember
		if err := rows.Scan(&m.UserID, &m.Name, &m.Email, &m.AccountRole, &m.OfficerReference, &m.MembershipActive,
			&m.PlatformActive, &m.Roles, &m.OpenCases); err != nil {
			return nil, err
		}
		if len(m.Roles) == 0 {
			if m.AccountRole == roleMFIAdmin {
				m.Roles = []string{RoleAdministrator}
			} else {
				m.Roles = []string{RoleLoanOfficer}
			}
		}
		team = append(team, m)
	}
	return team, rows.Err()
}

// SetTeamMember records a member's platform roles and access. Removing
// access keeps every past action; nothing is deleted.
func (s *Store) SetTeamMember(ctx context.Context, partnerID, userID string, roles []string, active bool, actorID, actorName, note string, now time.Time) error {
	for _, role := range roles {
		if _, ok := LenderRoleLabels[role]; !ok {
			return need("roles", "Choose roles from the list.")
		}
	}
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var member bool
		if err := tx.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM bt_mfi_membership mm JOIN partner p ON p.loan_lender_id = mm.mfi_id
  WHERE p.id = $1 AND mm.user_id = $2)`, partnerID, userID).Scan(&member); err != nil {
			return err
		}
		if !member {
			return need("user", "That person is not a member of your organisation.")
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.lender_member (partner_id, user_id, roles, active, updated_by, updated_by_name, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (partner_id, user_id) DO UPDATE SET roles = EXCLUDED.roles, active = EXCLUDED.active,
  updated_by = EXCLUDED.updated_by, updated_by_name = EXCLUDED.updated_by_name, updated_at = EXCLUDED.updated_at`,
			partnerID, userID, roles, active, actorID, actorName, now); err != nil {
			return err
		}
		id, err := NewID()
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.lender_member_event (id, partner_id, user_id, roles, active, actor_id, actor_name, note)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`, id, partnerID, userID, roles, active, actorID, actorName, note)
		return err
	})
}
