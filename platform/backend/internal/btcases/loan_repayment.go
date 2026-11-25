package btcases

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
)

const reminderHorizonDays = 7

// liveLoan is one disbursed, active or defaulted loan.
type liveLoan struct {
	id, schoolID, school, lender, frequency string
	disbursed, maturity                     *time.Time
	termMonths                              *int
}

// repaymentFollowUps is send_repayment_follow_up_reminders.
func repaymentFollowUps(ctx context.Context, tx pgx.Tx, today, now time.Time, n Notices) (int, error) {
	rows, err := tx.Query(ctx, `SELECT l.id, l.school_id, s.name, m.name, COALESCE(l.repayment_frequency, ''), l.disbursement_date,
  l.maturity_date, l.term_months
FROM bt_mfi_loan l JOIN school s ON s.id = l.school_id JOIN bt_mfi_organization m ON m.id = l.mfi_id
WHERE l.deleted_at IS NULL AND l.status = ANY($1)
ORDER BY l.disbursement_date DESC NULLS FIRST, l.created_at DESC`, liveLoanStatuses)
	if err != nil {
		return 0, fmt.Errorf("btcases: reading the live loans: %w", err)
	}
	var loans []liveLoan
	for rows.Next() {
		var l liveLoan
		if err := rows.Scan(&l.id, &l.schoolID, &l.school, &l.lender, &l.frequency, &l.disbursed, &l.maturity, &l.termMonths); err != nil {
			rows.Close()
			return 0, err
		}
		loans = append(loans, l)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	sent := 0
	for _, l := range loans {
		due, ok, err := derivedDueDate(ctx, tx, l, today)
		if err != nil {
			return sent, err
		}
		if !ok || due.After(today.AddDate(0, 0, reminderHorizonDays)) {
			continue
		}
		until := int(due.Sub(today).Hours() / 24)
		stage := "upcoming:" + due.Format(time.DateOnly)
		timing := fmt.Sprintf("due in %d day(s)", until)
		switch {
		case until < 0:
			stage = fmt.Sprintf("overdue:%s:w%d", due.Format(time.DateOnly), (-until)/7)
			timing = fmt.Sprintf("%d day(s) overdue", -until)
		case until == 0:
			timing = "due today"
		}
		frequency := l.frequency
		if frequency == "" {
			frequency = "scheduled"
		}
		people, err := applicationRecipients(ctx, tx, l.schoolID)
		if err != nil {
			return sent, err
		}
		for _, to := range people {
			first, err := claim(ctx, tx, "repayment_follow_up", l.id, stage, to.id, now)
			if err != nil {
				return sent, err
			}
			if !first {
				continue
			}
			if err := n.tell(ctx, tx, now, to, activities.Notice{
				Title: "Loan repayment follow-up · " + l.school,
				Body: fmt.Sprintf("The %s payment to %s is %s. Contact the school and record the repayment position.",
					frequency, l.lender, timing),
				Event: "bt.loan_repayment.follow_up", Category: "business_transformation", ContextType: "loan",
				Priority: "high",
			}, l.id); err != nil {
				return sent, err
			}
			sent++
		}
	}
	return sent, nil
}

// derivedDueDate is _derived_due_date: the latest repayment snapshot's next
// payment day; else, on an installment schedule, the earliest unpaid
// installment due by today when anything is overdue, or the next one due;
// else the next step after disbursement on a monthly or termly rhythm,
// capped at maturity.
func derivedDueDate(ctx context.Context, tx pgx.Tx, l liveLoan, today time.Time) (time.Time, bool, error) {
	var next *time.Time
	err := tx.QueryRow(ctx, `SELECT next_payment_date FROM bt_repayment_snapshot WHERE loan_id = $1
ORDER BY as_of_date DESC, created_at DESC LIMIT 1`, l.id).Scan(&next)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return time.Time{}, false, fmt.Errorf("btcases: reading the loan's repayment snapshot: %w", err)
	}
	if next != nil {
		return dayOnly(*next), true, nil
	}
	var version *int
	if err := tx.QueryRow(ctx, `SELECT max(schedule_version) FROM bt_loan_repayment_installment WHERE loan_id = $1`, l.id).
		Scan(&version); err != nil {
		return time.Time{}, false, fmt.Errorf("btcases: reading the loan's schedule: %w", err)
	}
	if version != nil && *version != 0 {
		overdue, err := anythingOverdue(ctx, tx, l.id, *version, today)
		if err != nil {
			return time.Time{}, false, err
		}
		sql := `SELECT due_date FROM bt_loan_repayment_installment WHERE loan_id = $1 AND schedule_version = $2 AND due_date >= $3
ORDER BY due_date LIMIT 1`
		if overdue {
			sql = `SELECT due_date FROM bt_loan_repayment_installment WHERE loan_id = $1 AND schedule_version = $2 AND due_date <= $3
ORDER BY due_date LIMIT 1`
		}
		var due time.Time
		err = tx.QueryRow(ctx, sql, l.id, *version, today.Format(time.DateOnly)).Scan(&due)
		if errors.Is(err, pgx.ErrNoRows) {
			return time.Time{}, false, nil
		}
		if err != nil {
			return time.Time{}, false, fmt.Errorf("btcases: reading the loan's next installment: %w", err)
		}
		return dayOnly(due), true, nil
	}
	if l.disbursed == nil {
		return time.Time{}, false, nil
	}
	var step int
	switch f := strings.ToLower(l.frequency); {
	case strings.Contains(f, "term") || strings.Contains(f, "quarter"):
		step = 3
	case strings.Contains(f, "month"):
		step = 1
	default:
		return time.Time{}, false, nil
	}
	start := dayOnly(*l.disbursed)
	due := addMonths(start, step)
	var maturity time.Time
	if l.maturity != nil {
		maturity = dayOnly(*l.maturity)
	} else {
		months := step
		if l.termMonths != nil && *l.termMonths != 0 {
			months = *l.termMonths
		}
		maturity = addMonths(start, months)
	}
	for due.Before(today) && due.Before(maturity) {
		due = addMonths(due, step)
	}
	if maturity.Before(due) {
		return maturity, true, nil
	}
	return due, true, nil
}

// anythingOverdue is loan_position's amountOverdue > 0: an installment of the
// schedule due by today with principal, interest or fee left after the
// payments (less reversals) allocated to it by today.
func anythingOverdue(ctx context.Context, tx pgx.Tx, loanID string, version int, today time.Time) (bool, error) {
	var overdue bool
	err := tx.QueryRow(ctx, `
WITH paid AS (
  SELECT a.installment_id, a.component,
         sum(CASE WHEN t.kind = 'payment' THEN a.amount WHEN t.kind = 'reversal' THEN -a.amount ELSE 0 END) AS net
  FROM bt_repayment_allocation a JOIN bt_repayment_transaction t ON t.id = a.transaction_id
  WHERE t.value_date <= $3
  GROUP BY a.installment_id, a.component
)
SELECT COALESCE(bool_or(
  GREATEST(0, i.principal_due - COALESCE((SELECT net FROM paid WHERE installment_id = i.id AND component = 'principal'), 0))
  + GREATEST(0, i.interest_due - COALESCE((SELECT net FROM paid WHERE installment_id = i.id AND component = 'interest'), 0))
  + GREATEST(0, i.fee_due - COALESCE((SELECT net FROM paid WHERE installment_id = i.id AND component = 'fee'), 0)) > 0
), false)
FROM bt_loan_repayment_installment i
WHERE i.loan_id = $1 AND i.schedule_version = $2 AND i.due_date <= $3`, loanID, version, today.Format(time.DateOnly)).Scan(&overdue)
	if err != nil {
		return false, fmt.Errorf("btcases: reading the loan's overdue position: %w", err)
	}
	return overdue, nil
}

// addMonths is _add_months: the same day, clamped to the month's last.
func addMonths(d time.Time, months int) time.Time {
	index := int(d.Month()) - 1 + months
	year := d.Year() + floorDiv(index, 12)
	month := time.Month(index - floorDiv(index, 12)*12 + 1)
	last := time.Date(year, month+1, 0, 0, 0, 0, 0, time.UTC).Day()
	day := d.Day()
	if day > last {
		day = last
	}
	return time.Date(year, month, day, 0, 0, 0, 0, time.UTC)
}

func floorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// monthlyReport is send_monthly_rvp_report: last month's loan report to each
// Regional Vice President once. The report reads the recipient's scope by
// the role they are working in; a Regional Vice President working in it
// reads every school and loan. One working in another role is passed over
// (logged, not claimed), since Go does not read that scope yet.
func monthlyReport(ctx context.Context, tx pgx.Tx, today, now time.Time, n Notices) (int, error) {
	end := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	start := end.AddDate(0, -1, 0)
	period := start.Format("2006-01")
	rows, err := tx.Query(ctx, `SELECT id, COALESCE(active_role, '') FROM "user" WHERE 'RegionalVicePresident' = ANY(roles)
  AND is_active AND deleted_at IS NULL ORDER BY created_at DESC`)
	if err != nil {
		return 0, fmt.Errorf("btcases: reading the Regional Vice Presidents: %w", err)
	}
	var people []recipient
	for rows.Next() {
		var r recipient
		if err := rows.Scan(&r.id, &r.activeRole); err != nil {
			rows.Close()
			return 0, err
		}
		people = append(people, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	sent := 0
	for _, to := range people {
		if to.activeRole != "RegionalVicePresident" {
			if n.Logger != nil {
				n.Logger.WarnContext(ctx, "btcases: the monthly loan report is left for the existing job: its reader works in another role",
					"user", to.id, "role", to.activeRole)
			}
			continue
		}
		first, err := claim(ctx, tx, "monthly_rvp_report", period, period, to.id, now)
		if err != nil {
			return sent, err
		}
		if !first {
			continue
		}
		s, err := reportSummary(ctx, tx, start, end)
		if err != nil {
			return sent, err
		}
		if err := n.tell(ctx, tx, now, to, activities.Notice{
			Title: "Monthly loan report ready · " + start.Format("January 2006"),
			Body: fmt.Sprintf("%d application(s), %d loan(s) disbursed worth UGX %s, and UGX %s in repayments. "+
				"Export CSV or Excel from the loan dashboard.", s.applications, s.loans, s.disbursed, s.repaid),
			Event: "bt.loan_report.monthly", Category: "business_transformation", ContextType: "loan_report_month",
			Priority: "normal",
		}, period); err != nil {
			return sent, err
		}
		sent++
	}
	return sent, nil
}

type summary struct {
	applications, loans int
	disbursed, repaid   string
}

// reportSummary is monthly_report_summary for a reader who sees every school
// and loan: the month's applications (by their Kampala submission day),
// loans disbursed and their value, and repayments less reversals.
func reportSummary(ctx context.Context, tx pgx.Tx, start, end time.Time) (summary, error) {
	var s summary
	var disbursed, payments, reversals string
	err := tx.QueryRow(ctx, `SELECT
  (SELECT count(*)::int FROM bt_loan_application a JOIN school sc ON sc.id = a.school_id
    WHERE a.deleted_at IS NULL AND sc.deleted_at IS NULL AND (a.submitted_at AT TIME ZONE 'Africa/Kampala')::date >= $1 AND (a.submitted_at AT TIME ZONE 'Africa/Kampala')::date < $2),
  (SELECT count(*)::int FROM bt_mfi_loan WHERE deleted_at IS NULL AND disbursement_date >= $1 AND disbursement_date < $2),
  (SELECT COALESCE(sum(disbursed_amount), 0)::text FROM bt_mfi_loan WHERE deleted_at IS NULL AND disbursement_date >= $1
     AND disbursement_date < $2),
  (SELECT COALESCE(sum(t.amount) FILTER (WHERE t.kind = 'payment'), 0)::text FROM bt_repayment_transaction t
     JOIN bt_mfi_loan l ON l.id = t.loan_id WHERE l.deleted_at IS NULL AND t.value_date >= $1 AND t.value_date < $2),
  (SELECT COALESCE(sum(t.amount) FILTER (WHERE t.kind = 'reversal'), 0)::text FROM bt_repayment_transaction t
     JOIN bt_mfi_loan l ON l.id = t.loan_id WHERE l.deleted_at IS NULL AND t.value_date >= $1 AND t.value_date < $2)`,
		start.Format(time.DateOnly), end.Format(time.DateOnly)).Scan(&s.applications, &s.loans, &disbursed, &payments, &reversals)
	if err != nil {
		return s, fmt.Errorf("btcases: reading the month's loan figures: %w", err)
	}
	d, err := pydecimal.Parse(disbursed)
	if err != nil {
		return s, err
	}
	p, err := pydecimal.Parse(payments)
	if err != nil {
		return s, err
	}
	r, err := pydecimal.Parse(reversals)
	if err != nil {
		return s, err
	}
	s.disbursed, s.repaid = grouped(d), grouped(p.Sub(r))
	return s, nil
}

// grouped is f"{value:,.0f}" of a Decimal: rounded half to even, thousands
// separated by commas.
func grouped(d pydecimal.Decimal) string {
	digits := d.Quantize(0).String()
	sign := ""
	if len(digits) > 0 && digits[0] == '-' {
		sign, digits = "-", digits[1:]
	}
	if i := strings.IndexByte(digits, '.'); i >= 0 {
		digits = digits[:i]
	}
	var out []byte
	for i := range digits {
		if i > 0 && (len(digits)-i)%3 == 0 {
			out = append(out, ',')
		}
		out = append(out, digits[i])
	}
	return sign + string(out)
}
