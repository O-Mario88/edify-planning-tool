package financeops

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestReconcileVarianceExactIntegerUGX(t *testing.T) {
	v, err := ReconcileVariance(450000, 425000, 25000)
	if err != nil || v != 0 {
		t.Fatalf("expected 0 variance, got v=%d err=%v", v, err)
	}
	v, err = ReconcileVariance(450000, 400000, 10000)
	if err != nil || v != 40000 {
		t.Fatalf("expected 40000 variance, got v=%d err=%v", v, err)
	}
	if _, err := ReconcileVariance(-1, 0, 0); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for negative disbursed amount, got %v", err)
	}
}

func TestTransitionWeeklyRequestRoleGuards(t *testing.T) {
	svc := NewService(nil)
	cceo := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "CCEO"}}
	if _, err := svc.TransitionWeeklyRequest(context.Background(), cceo, "w1", "disburse", 100000, 0, "momo", "ref-1", ""); !errors.Is(err, ErrForbidden) {
		t.Fatalf("expected ErrForbidden for CCEO disburse, got %v", err)
	}
	acct := auth.Principal{Account: auth.Account{UserID: "u2", ActiveRole: "Accountant"}}
	if _, err := svc.TransitionWeeklyRequest(context.Background(), acct, "w1", "disburse", 100000, 0, "momo", "", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for empty disburse reference, got %v", err)
	}
}
