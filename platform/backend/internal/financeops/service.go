// Package financeops implements native Go operational finance writes (M12):
// weekly fund requests, supervisor/CD approvals, idempotent disbursements,
// receipt confirmation, accountability, exact integer UGX variance
// reconciliation, and monthly work-plan budget transitions.
package financeops

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func withRW(ctx context.Context, pool *pgxpool.Pool, fn func(pgx.Tx) error) error {
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

var (
	ErrForbidden    = errors.New("financeops: actor is not permitted for this finance transition")
	ErrInvalidInput = errors.New("financeops: invalid finance input")
)

type Service struct {
	pool *pgxpool.Pool
	now  func() time.Time
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, now: time.Now}
}

// WithClock overrides the clock used for audit timestamps (useful in tests).
func (s *Service) WithClock(fn func() time.Time) *Service {
	if s != nil && fn != nil {
		s.now = fn
	}
	return s
}

func (s *Service) clock() time.Time {
	if s != nil && s.now != nil {
		return s.now().UTC()
	}
	return time.Now().UTC()
}

// ReconcileVariance returns the exact integer variance (disbursed - accounted - returned)
// in minor units (UGX) with zero floating-point error.
func ReconcileVariance(disbursed, accounted, returned int64) (int64, error) {
	if disbursed < 0 || accounted < 0 || returned < 0 {
		return 0, fmt.Errorf("%w: monetary amounts must be non-negative", ErrInvalidInput)
	}
	return disbursed - accounted - returned, nil
}

type WeeklySubmitRequest struct {
	FY            string
	WeekStart     time.Time
	WeekEnd       time.Time
	TotalAmount   int64
	FundingSource string
}

func (s *Service) SubmitWeeklyRequest(ctx context.Context, p auth.Principal, req WeeklySubmitRequest) (string, error) {
	if req.TotalAmount < 0 || strings.TrimSpace(req.FY) == "" || req.WeekStart.IsZero() {
		return "", fmt.Errorf("%w: fy, week_start, and non-negative total_amount are required", ErrInvalidInput)
	}
	var id string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT gateway_finance.submit_weekly_request($1,$2::date,$3::date,$4,$5,$6,$7)`,
			req.FY, req.WeekStart.Format("2006-01-02"), req.WeekEnd.Format("2006-01-02"),
			p.UserID, req.TotalAmount, req.FundingSource, p.ActiveRole).Scan(&id); err != nil {
			return err
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "finance.weekly_request.submit",
			SubjectKind: audit.Text("weekly_fund_request"),
			SubjectID:   audit.Text(id),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"total_amount": req.TotalAmount,
				"week_start":   req.WeekStart.Format("2006-01-02"),
			},
		}, s.clock())
		return err
	})
	return id, err
}

type TransitionResult struct {
	Status  string
	Applied bool
}

func (s *Service) TransitionWeeklyRequest(
	ctx context.Context, p auth.Principal, requestID, action string,
	amount, returned int64, method, reference, reason string,
) (TransitionResult, error) {
	if err := checkWeeklyRole(p.ActiveRole, action); err != nil {
		return TransitionResult{}, err
	}
	if amount < 0 || returned < 0 {
		return TransitionResult{}, fmt.Errorf("%w: negative monetary amount refused", ErrInvalidInput)
	}
	if action == "return" && strings.TrimSpace(reason) == "" {
		return TransitionResult{}, fmt.Errorf("%w: return reason is required", ErrInvalidInput)
	}
	if action == "disburse" && strings.TrimSpace(reference) == "" {
		return TransitionResult{}, fmt.Errorf("%w: disburse reference (idempotency key) is required", ErrInvalidInput)
	}
	var out TransitionResult
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT new_status, applied FROM gateway_finance.transition_weekly_request($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
			requestID, action, p.UserID, p.ActiveRole, amount, returned,
			strings.TrimSpace(method), strings.TrimSpace(reference), strings.TrimSpace(reason)).
			Scan(&out.Status, &out.Applied); err != nil {
			return err
		}
		if !out.Applied {
			return nil
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "finance.weekly_request." + action,
			SubjectKind: audit.Text("weekly_fund_request"),
			SubjectID:   audit.Text(requestID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"new_status": out.Status,
				"amount":     amount,
				"returned":   returned,
				"ref":        strings.TrimSpace(reference),
			},
		}, s.clock())
		return err
	})
	return out, err
}

func checkWeeklyRole(role, action string) error {
	switch action {
	case "approve_pl":
		if role != "Program Lead" && role != "Admin" {
			return ErrForbidden
		}
	case "approve_cd":
		if role != "CountryDirector" && role != "Admin" {
			return ErrForbidden
		}
	case "disburse":
		if role != "Accountant" && role != "Admin" {
			return ErrForbidden
		}
	case "return":
		if role != "Program Lead" && role != "CountryDirector" && role != "Accountant" && role != "Admin" {
			return ErrForbidden
		}
	case "confirm_receipt", "submit_accountability":
		// Request owner or Admin.
	default:
		return fmt.Errorf("%w: unknown action %q", ErrInvalidInput, action)
	}
	return nil
}

func (s *Service) DecideMonthlyBudget(ctx context.Context, p auth.Principal, budgetID, newStatus, note string) (string, error) {
	if p.ActiveRole != "CountryDirector" && p.ActiveRole != "RegionalVicePresident" && p.ActiveRole != "Admin" {
		return "", ErrForbidden
	}
	var out string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT gateway_finance.decide_monthly_budget($1,$2,$3,$4,$5)`,
			budgetID, strings.TrimSpace(newStatus), p.UserID, p.ActiveRole, strings.TrimSpace(note)).Scan(&out); err != nil {
			return err
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "finance.monthly_budget." + out,
			SubjectKind: audit.Text("monthly_work_plan_budget"),
			SubjectID:   audit.Text(budgetID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"new_status": out,
				"note":       strings.TrimSpace(note),
			},
		}, s.clock())
		return err
	})
	return out, err
}

func (s *Service) TransitionAdvance(
	ctx context.Context, p auth.Principal, advanceID, action string,
	amount, returned int64, method, reference string,
) (TransitionResult, error) {
	if (action == "disburse" || action == "verify_return") && p.ActiveRole != "Accountant" && p.ActiveRole != "Admin" {
		return TransitionResult{}, ErrForbidden
	}
	if amount < 0 || returned < 0 {
		return TransitionResult{}, fmt.Errorf("%w: negative monetary amount refused", ErrInvalidInput)
	}
	var out TransitionResult
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT new_status, applied FROM gateway_finance.transition_advance($1,$2,$3,$4,$5,$6,$7,$8)`,
			advanceID, action, p.UserID, p.ActiveRole, amount, returned,
			strings.TrimSpace(method), strings.TrimSpace(reference)).Scan(&out.Status, &out.Applied); err != nil {
			return err
		}
		if !out.Applied {
			return nil
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "finance.advance." + action,
			SubjectKind: audit.Text("advance_request"),
			SubjectID:   audit.Text(advanceID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"new_status": out.Status,
				"amount":     amount,
				"returned":   returned,
				"ref":        strings.TrimSpace(reference),
			},
		}, s.clock())
		return err
	})
	return out, err
}
