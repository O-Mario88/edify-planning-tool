package workforceops

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestDecideLeaveRBACAndValidation(t *testing.T) {
	svc := NewService(nil)
	for _, role := range []string{"CCEO", "ClusterLeader", "PartnerFieldOfficer", "Accountant", "ImpactAssessment"} {
		p := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: role}}
		if _, err := svc.DecideLeave(context.Background(), p, "lv-1", "approved", ""); !errors.Is(err, ErrForbidden) {
			t.Errorf("DecideLeave: expected ErrForbidden for role %q, got %v", role, err)
		}
	}
	pl := auth.Principal{Account: auth.Account{UserID: "pl-1", ActiveRole: "Program Lead"}}
	if _, err := svc.DecideLeave(context.Background(), pl, "lv-1", "bogus", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("DecideLeave: expected ErrInvalidInput for bogus decision, got %v", err)
	}
}

func TestDecideEscalationRBACAndValidation(t *testing.T) {
	svc := NewService(nil)
	for _, role := range []string{"CCEO", "ClusterLeader", "Accountant", "HumanResources", "PartnerAdmin"} {
		p := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: role}}
		if _, err := svc.DecideEscalation(context.Background(), p, "esc-1", "resolved", ""); !errors.Is(err, ErrForbidden) {
			t.Errorf("DecideEscalation: expected ErrForbidden for role %q, got %v", role, err)
		}
	}
	cd := auth.Principal{Account: auth.Account{UserID: "cd-1", ActiveRole: "CountryDirector"}}
	if _, err := svc.DecideEscalation(context.Background(), cd, "esc-1", "   ", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("DecideEscalation: expected ErrInvalidInput for blank decision, got %v", err)
	}
}

func TestRaiseEscalationValidationAndRBAC(t *testing.T) {
	svc := NewService(nil)
	for _, role := range []string{"ClusterLeader", "MfiLoanOfficer", "MfiPartnerAdmin"} {
		p := auth.Principal{Account: auth.Account{UserID: "ext-1", ActiveRole: role}}
		if _, err := svc.RaiseEscalation(context.Background(), p, "ops", "high", "Subject", "Detail", "", ""); !errors.Is(err, ErrForbidden) {
			t.Errorf("RaiseEscalation: expected ErrForbidden for role %q, got %v", role, err)
		}
	}
	cceo := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "CCEO"}}
	if _, err := svc.RaiseEscalation(context.Background(), cceo, "ops", "high", "", "detail", "", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for empty subject, got %v", err)
	}
	if _, err := svc.RaiseEscalation(context.Background(), cceo, "ops", "high", "Subject", "Detail", "", "not-a-date"); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for invalid due_date, got %v", err)
	}
}

func TestRequestLeaveValidationAndRBAC(t *testing.T) {
	svc := NewService(nil)
	for _, role := range []string{"ClusterLeader", "PartnerAdmin", "PartnerFieldOfficer", "MfiLoanOfficer", "MfiPartnerAdmin"} {
		p := auth.Principal{Account: auth.Account{UserID: "ext-1", ActiveRole: role}}
		if _, err := svc.RequestLeave(context.Background(), p, "annual", "2026-12-01", "2026-12-03", "rest", "colleague"); !errors.Is(err, ErrForbidden) {
			t.Errorf("RequestLeave: expected ErrForbidden for external role %q, got %v", role, err)
		}
	}
	cceo := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "CCEO"}}
	if _, err := svc.RequestLeave(context.Background(), cceo, "", "2026-12-01", "2026-12-03", "rest", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for empty leaveType, got %v", err)
	}
	if _, err := svc.RequestLeave(context.Background(), cceo, "annual", "2026-12-05", "2026-12-01", "rest", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput when end_date < start_date, got %v", err)
	}
	if _, err := svc.RequestLeave(context.Background(), cceo, "annual", "2026-01-01", "2027-06-01", "long", ""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput when duration > 365 days, got %v", err)
	}
}
