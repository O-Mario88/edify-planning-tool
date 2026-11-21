package loans

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

func withLoanRW(ctx context.Context, pool *pgxpool.Pool, fn func(pgx.Tx) error) error {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// NativeLedger writes loan referrals, disbursements, schedules, and repayments
// directly into PostgreSQL through narrow SECURITY DEFINER functions in
// gateway_loans_ledger with strict idempotency-key deduplication (Batch 10).
// Replaces LedgerClient when Django is absent.
type NativeLedger struct {
	pool *pgxpool.Pool
}

// NewNativeLedger constructs a Django-independent loan ledger writer.
func NewNativeLedger(pool *pgxpool.Pool) *NativeLedger {
	return &NativeLedger{pool: pool}
}

func actorFrom(ctx context.Context) string {
	if p, ok := auth.PrincipalFrom(ctx); ok && p.UserID != "" {
		return p.UserID
	}
	return "system"
}

func (n *NativeLedger) CreateReferral(ctx context.Context, r ReferralRequest) (string, error) {
	if n.pool == nil {
		return "", ErrLedgerUnavailable
	}
	var id string
	err := withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_loans_ledger.create_referral($1, $2, $3, $4::numeric, $5, $6, $7)`,
			r.CaseID, r.MFIID, r.PurposeID, r.Requested.String(), r.IntendedUse,
			r.ConsentRecordedAt.UTC(), actorFrom(ctx)).Scan(&id)
	})
	if err != nil {
		return "", fmt.Errorf("loans: native create referral: %w", err)
	}
	return id, nil
}

func (n *NativeLedger) RegisterLoan(ctx context.Context, r LoanRegistration) (string, error) {
	if n.pool == nil {
		return "", ErrLedgerUnavailable
	}
	var id string
	err := withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_loans_ledger.register_loan($1, $2, $3, $4::numeric, $5::numeric, $6, $7)`,
			r.ReferralID, r.ExternalReference, r.OfficerReference,
			r.Approved.String(), r.Requested.String(), r.TermMonths, actorFrom(ctx)).Scan(&id)
	})
	if err != nil {
		return "", fmt.Errorf("loans: native register loan: %w", err)
	}
	return id, nil
}

func (n *NativeLedger) ReserveFacility(ctx context.Context, facilityID, loanID string, amount ledger.Money, key string) (string, error) {
	if n.pool == nil {
		return "", ErrLedgerUnavailable
	}
	var id string
	err := withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_loans_ledger.reserve_facility($1, $2, $3::numeric, $4, $5)`,
			facilityID, loanID, amount.String(), strings.TrimSpace(key), actorFrom(ctx)).Scan(&id)
	})
	if err != nil {
		return "", fmt.Errorf("loans: native reserve facility: %w", err)
	}
	return id, nil
}

func (n *NativeLedger) PostDisbursement(ctx context.Context, d DisbursementPosting) (string, error) {
	if n.pool == nil {
		return "", ErrLedgerUnavailable
	}
	var id string
	err := withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_loans_ledger.post_disbursement($1, $2, $3, $4, $5::numeric, $6, $7::date, $8::date, $9)`,
			d.LoanID, strings.TrimSpace(d.IdempotencyKey), d.ExternalReference, d.BankReference,
			d.Amount.String(), d.Sequence, d.DisbursedOn.Format("2006-01-02"), d.ValueDate.Format("2006-01-02"),
			actorFrom(ctx)).Scan(&id)
	})
	if err != nil {
		return "", fmt.Errorf("loans: native post disbursement: %w", err)
	}
	return id, nil
}

func (n *NativeLedger) PostSchedule(ctx context.Context, loanID string, version int, rows []ledger.Installment) error {
	if n.pool == nil {
		return ErrLedgerUnavailable
	}
	type item struct {
		Number    int    `json:"number"`
		DueDate   string `json:"due_date"`
		Principal string `json:"principal"`
		Interest  string `json:"interest"`
		Fee       string `json:"fee"`
	}
	items := make([]item, len(rows))
	for i, r := range rows {
		items[i] = item{
			Number:    r.Number,
			DueDate:   r.DueDate.Format("2006-01-02"),
			Principal: r.Principal.String(),
			Interest:  r.Interest.String(),
			Fee:       r.Fee.String(),
		}
	}
	payload, err := json.Marshal(items)
	if err != nil {
		return err
	}
	err = withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`SELECT gateway_loans_ledger.post_schedule($1, $2, $3::jsonb, $4)`,
			loanID, version, string(payload), actorFrom(ctx))
		return err
	})
	if err != nil {
		return fmt.Errorf("loans: native post schedule: %w", err)
	}
	return nil
}

func (n *NativeLedger) PostRepayment(ctx context.Context, r RepaymentPosting) (string, error) {
	if n.pool == nil {
		return "", ErrLedgerUnavailable
	}
	type alloc struct {
		InstallmentID string `json:"installment_id"`
		Component     string `json:"component"`
		Amount        string `json:"amount"`
	}
	allocs := make([]alloc, len(r.Allocations))
	for i, a := range r.Allocations {
		allocs[i] = alloc{
			InstallmentID: a.InstallmentID,
			Component:     string(a.Component),
			Amount:        a.Amount.String(),
		}
	}
	payload, err := json.Marshal(allocs)
	if err != nil {
		return "", err
	}
	var id string
	err = withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_loans_ledger.post_repayment($1, $2, $3, $4, $5::numeric, $6::date, $7::date, $8::jsonb, $9)`,
			r.LoanID, strings.TrimSpace(r.IdempotencyKey), r.ExternalReference, r.EvidenceReference,
			r.Amount.String(), r.ReceivedOn.Format("2006-01-02"), r.ValueDate.Format("2006-01-02"),
			string(payload), actorFrom(ctx)).Scan(&id)
	})
	if err != nil {
		return "", fmt.Errorf("loans: native post repayment: %w", err)
	}
	return id, nil
}

func (n *NativeLedger) ReverseRepayment(ctx context.Context, transactionID, key, reason, reference, evidence string) (string, error) {
	if n.pool == nil {
		return "", ErrLedgerUnavailable
	}
	var id string
	err := withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_loans_ledger.reverse_repayment($1, $2, $3, $4, $5, $6)`,
			transactionID, strings.TrimSpace(key), reason, reference, evidence, actorFrom(ctx)).Scan(&id)
	})
	if err != nil {
		return "", fmt.Errorf("loans: native reverse repayment: %w", err)
	}
	return id, nil
}

func (n *NativeLedger) SetOfficerReference(ctx context.Context, mfiID, userID, reference string) error {
	if n.pool == nil {
		return ErrLedgerUnavailable
	}
	return withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`SELECT gateway_loans_ledger.set_officer_reference($1, $2, $3)`,
			mfiID, userID, strings.TrimSpace(reference))
		return err
	})
}

func (n *NativeLedger) SetPurposePlan(ctx context.Context, loanID string, lines []PurposeLine) error {
	if n.pool == nil {
		return ErrLedgerUnavailable
	}
	type row struct {
		PurposeID      string `json:"purpose_id"`
		Amount         string `json:"amount"`
		IntendedOutput string `json:"intended_output"`
	}
	rows := make([]row, len(lines))
	for i, l := range lines {
		rows[i] = row{PurposeID: l.PurposeID, Amount: l.Amount.String(), IntendedOutput: l.IntendedOutput}
	}
	payload, err := json.Marshal(rows)
	if err != nil {
		return err
	}
	return withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`SELECT gateway_loans_ledger.set_purpose_plan($1, $2::jsonb, $3)`,
			loanID, string(payload), actorFrom(ctx))
		return err
	})
}

func (n *NativeLedger) RecordEnrolmentBaseline(ctx context.Context, loanID string, learners int, asOf time.Time, cohort, evidence string) error {
	if n.pool == nil {
		return ErrLedgerUnavailable
	}
	return withLoanRW(ctx, n.pool, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`SELECT gateway_loans_ledger.record_enrolment_baseline($1, $2, $3::date, $4, $5, $6)`,
			loanID, learners, asOf.Format("2006-01-02"), cohort, evidence, actorFrom(ctx))
		return err
	})
}
