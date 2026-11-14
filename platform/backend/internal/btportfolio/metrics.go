package btportfolio

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// LoanFrom is the loans' FROM clause the scope and filter conditions read.
const LoanFrom = `bt_mfi_loan l LEFT JOIN school s ON s.id = l.school_id LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id`

// Metrics is the part of portfolio_metrics the pages read.
type Metrics struct {
	FY                                                                 string
	LoansDisbursed, SchoolsImpacted                                    int
	EdtechLoans                                                        int
	ValueDisbursed                                                     ledger.Money
	Outstanding, PAR30, PAR90                                          ledger.Money
	AmountDue, AmountCollected                                         ledger.Money
	InstallmentsDue, InstallmentsOnTime                                int
	VerificationDue, VerificationDone, StudentsReached, PositiveImpact int
	LedgerLoans                                                        int
}

// money reads a numeric sum exactly; a NULL sum is zero.
func money(raw *string) (ledger.Money, error) {
	if raw == nil {
		return 0, nil
	}
	return ledger.ParseMoney(*raw)
}

func day(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }

// ScopedLoanIDs is the reader's loans under the filters.
func ScopedLoanIDs(ctx context.Context, db schooldirectory.Querier, p auth.Principal, f Filters, now time.Time) ([]string, error) {
	a := &Args{}
	where, err := LoansWhere(ctx, db, p, now, a)
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT l.id FROM `+LoanFrom+` WHERE `+where+FilterLoans(f, a), *a...)
	if err != nil {
		return nil, fmt.Errorf("btportfolio: reading the scoped loans: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("btportfolio: reading the scoped loans: %w", err)
	}
	if ids == nil {
		ids = []string{}
	}
	return ids, nil
}

// PortfolioMetrics is portfolio_metrics over the reader's filtered loans.
func PortfolioMetrics(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, f Filters, now time.Time) (Metrics, error) {
	m := Metrics{FY: fy}
	ids, err := ScopedLoanIDs(ctx, db, p, f, now)
	if err != nil {
		return m, err
	}
	start, end := Period(fy, f)
	var value *string
	if err := db.QueryRow(ctx, `SELECT count(DISTINCT d.loan_id), sum(d.amount)::text, count(DISTINCT l.school_id),
  count(DISTINCT d.loan_id) FILTER (WHERE p.is_edtech)
FROM bt_loan_disbursement d JOIN bt_mfi_loan l ON l.id = d.loan_id LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id
WHERE d.loan_id = ANY($1) AND NOT EXISTS (SELECT 1 FROM bt_loan_disbursement_reversal r WHERE r.disbursement_id = d.id)
  AND d.value_date >= $2::date AND d.value_date < $3::date`, ids, start.Format(time.DateOnly), end.Format(time.DateOnly)).
		Scan(&m.LoansDisbursed, &value, &m.SchoolsImpacted, &m.EdtechLoans); err != nil {
		return m, fmt.Errorf("btportfolio: reading the disbursements: %w", err)
	}
	if m.ValueDisbursed, err = money(value); err != nil {
		return m, err
	}
	rows, err := db.Query(ctx, `SELECT DISTINCT loan_id FROM bt_loan_disbursement WHERE loan_id = ANY($1)`, ids)
	if err != nil {
		return m, fmt.Errorf("btportfolio: reading the ledger's loans: %w", err)
	}
	ledgerLoans, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return m, fmt.Errorf("btportfolio: reading the ledger's loans: %w", err)
	}
	m.LedgerLoans = len(ledgerLoans)
	local := now.In(zone)
	periodEnd := day(end.AddDate(0, 0, -1))
	asOf := day(local)
	if periodEnd.Before(asOf) {
		asOf = periodEnd
	}
	r, err := ratios(ctx, db, ledgerLoans, day(start), periodEnd, asOf)
	if err != nil {
		return m, err
	}
	m.Outstanding, m.PAR30, m.PAR90 = r.outstanding, r.par30, r.par90
	m.AmountDue, m.AmountCollected = r.due, r.collected
	m.InstallmentsDue, m.InstallmentsOnTime = r.installmentsDue, r.onTime
	if err := db.QueryRow(ctx, `SELECT count(*), count(*) FILTER (WHERE status = 'verified') FROM bt_loan_verification_requirement
WHERE loan_id = ANY($1) AND due_date <= $2::date`, ids, day(local).Format(time.DateOnly)).Scan(&m.VerificationDue, &m.VerificationDone); err != nil {
		return m, fmt.Errorf("btportfolio: counting the loan-use verifications: %w", err)
	}
	// Reach: each financed school's latest verified baseline enrolment over
	// the loans disbursed in the period.
	if err := db.QueryRow(ctx, `WITH disbursed AS (
  SELECT l.id, l.school_id FROM bt_mfi_loan l WHERE l.id = ANY($1) AND EXISTS (
    SELECT 1 FROM bt_loan_disbursement d WHERE d.loan_id = l.id AND d.value_date >= $2::date AND d.value_date < $3::date
      AND NOT EXISTS (SELECT 1 FROM bt_loan_disbursement_reversal r WHERE r.disbursement_id = d.id)))
SELECT COALESCE(sum((SELECT e.learner_count FROM bt_enrolment_snapshot e JOIN disbursed x ON x.id = e.loan_id
  WHERE x.school_id = s.school_id AND e.kind = 'baseline' AND e.status = 'verified' ORDER BY e.as_of_date DESC, e.created_at DESC LIMIT 1)), 0)
FROM (SELECT DISTINCT school_id FROM disbursed) s`, ids, start.Format(time.DateOnly), end.Format(time.DateOnly)).Scan(&m.StudentsReached); err != nil {
		return m, fmt.Errorf("btportfolio: counting the students reached: %w", err)
	}
	if err := db.QueryRow(ctx, `SELECT count(DISTINCT loan_id) FROM bt_loan_impact_assessment
WHERE loan_id = ANY($1) AND ia_status = 'verified' AND classification = ANY($2)`, ids, Rules.PositiveImpact).Scan(&m.PositiveImpact); err != nil {
		return m, fmt.Errorf("btportfolio: counting the positive impact conclusions: %w", err)
	}
	return m, nil
}

type ratioSet struct {
	outstanding, par30, par90, due, collected ledger.Money
	installmentsDue, onTime                   int
}

// ratios is lending_ledger.portfolio_ratios.
func ratios(ctx context.Context, db schooldirectory.Querier, ids []string, periodStart, periodEnd, asOf time.Time) (ratioSet, error) {
	var r ratioSet
	if len(ids) == 0 {
		return r, nil
	}
	asOfText, startText, endText := asOf.Format(time.DateOnly), periodStart.Format(time.DateOnly), periodEnd.Format(time.DateOnly)
	outstanding := map[string]ledger.Money{}
	rows, err := db.Query(ctx, `WITH ids AS (SELECT unnest($1::varchar[]) AS id),
disbursed AS (SELECT loan_id, sum(amount) AS total FROM bt_loan_disbursement d
  WHERE loan_id = ANY($1) AND value_date <= $2::date AND NOT EXISTS (SELECT 1 FROM bt_loan_disbursement_reversal v WHERE v.disbursement_id = d.id)
  GROUP BY loan_id),
repaid AS (SELECT t.loan_id, sum(a.amount) FILTER (WHERE t.kind = 'payment') AS paid, sum(a.amount) FILTER (WHERE t.kind = 'reversal') AS reversed
  FROM bt_repayment_allocation a JOIN bt_repayment_transaction t ON t.id = a.transaction_id
  WHERE t.loan_id = ANY($1) AND t.value_date <= $2::date AND a.component = 'principal' GROUP BY t.loan_id)
SELECT ids.id, COALESCE(d.total, 0)::text, COALESCE(r.paid, 0)::text, COALESCE(r.reversed, 0)::text
FROM ids LEFT JOIN disbursed d ON d.loan_id = ids.id LEFT JOIN repaid r ON r.loan_id = ids.id`, ids, asOfText)
	if err != nil {
		return r, fmt.Errorf("btportfolio: reading the outstanding principal: %w", err)
	}
	for rows.Next() {
		var id string
		var d, paid, back string
		if err := rows.Scan(&id, &d, &paid, &back); err != nil {
			rows.Close()
			return r, fmt.Errorf("btportfolio: reading the outstanding principal: %w", err)
		}
		dm, _ := ledger.ParseMoney(d)
		pm, _ := ledger.ParseMoney(paid)
		bm, _ := ledger.ParseMoney(back)
		outstanding[id] = max(0, dm-(pm-bm))
		r.outstanding += outstanding[id]
	}
	rows.Close()
	dueLimit := asOf
	if periodEnd.After(dueLimit) {
		dueLimit = periodEnd
	}
	rows, err = db.Query(ctx, `SELECT i.id, i.loan_id, i.due_date, (i.principal_due + i.interest_due + i.fee_due)::text,
  COALESCE((SELECT sum(a.amount) FILTER (WHERE t.kind = 'payment') - COALESCE(sum(a.amount) FILTER (WHERE t.kind = 'reversal'), 0)
     FROM bt_repayment_allocation a JOIN bt_repayment_transaction t ON t.id = a.transaction_id
     WHERE a.installment_id = i.id AND t.value_date <= $2::date), 0)::text,
  COALESCE((SELECT sum(a.amount) FILTER (WHERE t.kind = 'payment') - COALESCE(sum(a.amount) FILTER (WHERE t.kind = 'reversal'), 0)
     FROM bt_repayment_allocation a JOIN bt_repayment_transaction t ON t.id = a.transaction_id
     WHERE a.installment_id = i.id AND t.value_date <= i.due_date), 0)::text
FROM bt_loan_repayment_installment i
WHERE i.loan_id = ANY($1) AND i.due_date <= $3::date
  AND i.schedule_version = (SELECT max(schedule_version) FROM bt_loan_repayment_installment x WHERE x.loan_id = i.loan_id)`,
		ids, asOfText, dueLimit.Format(time.DateOnly))
	if err != nil {
		return r, fmt.Errorf("btportfolio: reading the installments: %w", err)
	}
	earliest := map[string]time.Time{}
	for rows.Next() {
		var id, loan, scheduled, allocated, onTime string
		var due time.Time
		if err := rows.Scan(&id, &loan, &due, &scheduled, &allocated, &onTime); err != nil {
			rows.Close()
			return r, fmt.Errorf("btportfolio: reading the installments: %w", err)
		}
		s, _ := ledger.ParseMoney(scheduled)
		al, _ := ledger.ParseMoney(allocated)
		ot, _ := ledger.ParseMoney(onTime)
		if !due.After(asOf) && al < s {
			if e, ok := earliest[loan]; !ok || due.Before(e) {
				earliest[loan] = due
			}
		}
		if !due.Before(periodStart) && !due.After(periodEnd) {
			r.installmentsDue++
			r.due += s
			if ot >= s {
				r.onTime++
			}
		}
	}
	rows.Close()
	for loan, due := range earliest {
		late := int(asOf.Sub(due).Hours() / 24)
		if late > 30 {
			r.par30 += outstanding[loan]
		}
		if late > 90 {
			r.par90 += outstanding[loan]
		}
	}
	var collected *string
	if err := db.QueryRow(ctx, `SELECT (COALESCE(sum(a.amount) FILTER (WHERE t.kind = 'payment'), 0) - COALESCE(sum(a.amount) FILTER (WHERE t.kind = 'reversal'), 0))::text
FROM bt_repayment_allocation a JOIN bt_repayment_transaction t ON t.id = a.transaction_id
WHERE t.loan_id = ANY($1) AND t.value_date >= $2::date AND t.value_date <= $3::date`, ids, startText, endText).Scan(&collected); err != nil {
		return r, fmt.Errorf("btportfolio: reading the collections: %w", err)
	}
	if r.collected, err = money(collected); err != nil {
		return r, err
	}
	return r, nil
}
