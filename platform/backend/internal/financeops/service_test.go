package financeops

import (
	"context"
	"errors"
	"testing"
	"time"

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
	// Separation of duties: ImpactAssessment cannot approve CD or disburse.
	ia := auth.Principal{Account: auth.Account{UserID: "u3", ActiveRole: "ImpactAssessment"}}
	if _, err := svc.TransitionWeeklyRequest(context.Background(), ia, "w1", "disburse", 50000, 0, "momo", "ref-2", ""); !errors.Is(err, ErrForbidden) {
		t.Fatalf("expected ErrForbidden for IA disburse, got %v", err)
	}
	if _, err := svc.TransitionWeeklyRequest(context.Background(), ia, "w1", "approve_cd", 50000, 0, "", "", ""); !errors.Is(err, ErrForbidden) {
		t.Fatalf("expected ErrForbidden for IA approve_cd, got %v", err)
	}
}

func TestSubmitWeeklyRequestAndAdvanceRoleGuards(t *testing.T) {
	svc := NewService(nil)
	for _, role := range []string{"ClusterLeader", "PartnerFieldOfficer", "PartnerAdmin", "MfiLoanOfficer", "MfiPartnerAdmin"} {
		p := auth.Principal{Account: auth.Account{UserID: "ext-1", ActiveRole: role}}
		_, err := svc.SubmitWeeklyRequest(context.Background(), p, WeeklySubmitRequest{
			FY: "2027", WeekStart: time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC), TotalAmount: 10000,
		})
		if !errors.Is(err, ErrForbidden) {
			t.Errorf("SubmitWeeklyRequest: expected ErrForbidden for role %q, got %v", role, err)
		}
		_, err = svc.TransitionAdvance(context.Background(), p, "adv-1", "confirm_receipt", 10000, 0, "", "")
		if !errors.Is(err, ErrForbidden) {
			t.Errorf("TransitionAdvance: expected ErrForbidden for role %q, got %v", role, err)
		}
	}
	cceo := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "CCEO"}}
	if _, err := svc.TransitionAdvance(context.Background(), cceo, "adv-1", "bogus_action", 0, 0, "", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for unknown advance action, got %v", err)
	}
	if _, err := svc.TransitionAdvance(context.Background(), cceo, "adv-1", "reimburse", 5000, 0, "momo", "ref-r"); !errors.Is(err, ErrForbidden) {
		t.Fatalf("expected ErrForbidden for CCEO reimburse, got %v", err)
	}
}
