package btcases

// `bt.activity.state_changed` is project_activity_state: a loan-use
// verification visit's requirement and result follow the visit's IA state.
// Verified (IA verified, accountant confirmed, closed): a recorded result is
// confirmed at the visit's IA confirmation time and the requirement verified,
// and the result's "evidence submitted" notices are resolved; with no result
// the requirement waits for verification, since an IA verdict on the visit
// cannot make a loan-use finding. Returned: the result is provisional again
// and the requirement waits for verification. Any other state changes
// nothing. Inside the caller's transaction; replay converges on the same
// rows.

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	requirementAwaiting = "awaiting_verification"
	requirementVerified = "verified"
	// evidenceSubmittedEvent is the notice a verified result resolves.
	evidenceSubmittedEvent = "bt.loan.use_evidence_submitted"
)

var (
	verifiedActivityStates = []string{"ia_verified", "accountant_confirmed", "closed"}
	returnedActivityStates = []string{"returned", "returned_by_ia", "returned_by_pl"}
)

// ProjectActivityState is the handler for one activity.
func ProjectActivityState(ctx context.Context, tx pgx.Tx, activityID string, now time.Time) error {
	var status string
	var iaConfirmedAt *time.Time
	err := tx.QueryRow(ctx, `SELECT status, ia_confirmed_at FROM activity WHERE id = $1 AND deleted_at IS NULL`, activityID).
		Scan(&status, &iaConfirmedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("btcases: reading the activity: %w", err)
	}
	var requirementID string
	err = tx.QueryRow(ctx, `SELECT id FROM bt_loan_verification_requirement WHERE activity_id = $1
ORDER BY due_date LIMIT 1 FOR UPDATE`, activityID).Scan(&requirementID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("btcases: locking the loan verification: %w", err)
	}
	var resultID *string
	if err := tx.QueryRow(ctx, `SELECT id FROM bt_loan_use_result WHERE requirement_id = $1`, requirementID).
		Scan(&resultID); err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("btcases: reading the loan-use result: %w", err)
	}
	switch {
	case in(status, verifiedActivityStates) && resultID == nil:
		return setRequirement(ctx, tx, `UPDATE bt_loan_verification_requirement SET status = $2, updated_at = $3 WHERE id = $1`,
			requirementID, requirementAwaiting, now)
	case in(status, verifiedActivityStates):
		verifiedAt := now
		if iaConfirmedAt != nil {
			verifiedAt = *iaConfirmedAt
		}
		if _, err := tx.Exec(ctx, `UPDATE bt_loan_use_result SET verification_status = 'confirmed', ia_verified_at = $2,
  updated_at = $3 WHERE id = $1`, *resultID, verifiedAt, now); err != nil {
			return fmt.Errorf("btcases: confirming the loan-use result: %w", err)
		}
		if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'LoanUseResult', $2, $3)`,
			evidenceSubmittedEvent, *resultID, now); err != nil {
			return fmt.Errorf("btcases: resolving the evidence notices: %w", err)
		}
		return setRequirement(ctx, tx, `UPDATE bt_loan_verification_requirement SET status = $2, verified_at = $4,
  updated_at = $3 WHERE id = $1`, requirementID, requirementVerified, now, verifiedAt)
	case in(status, returnedActivityStates):
		if resultID != nil {
			if _, err := tx.Exec(ctx, `UPDATE bt_loan_use_result SET verification_status = 'provisional', ia_verified_at = NULL,
  updated_at = $2 WHERE id = $1`, *resultID, now); err != nil {
				return fmt.Errorf("btcases: reopening the loan-use result: %w", err)
			}
		}
		return setRequirement(ctx, tx, `UPDATE bt_loan_verification_requirement SET status = $2, verified_at = NULL,
  updated_at = $3 WHERE id = $1`, requirementID, requirementAwaiting, now)
	}
	return nil
}

func setRequirement(ctx context.Context, tx pgx.Tx, sql string, args ...any) error {
	if _, err := tx.Exec(ctx, sql, args...); err != nil {
		return fmt.Errorf("btcases: updating the loan verification: %w", err)
	}
	return nil
}

func in(s string, set []string) bool {
	for _, v := range set {
		if v == s {
			return true
		}
	}
	return false
}
