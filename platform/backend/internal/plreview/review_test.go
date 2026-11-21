package plreview

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestCanReviewRole(t *testing.T) {
	for _, allowed := range []string{"Program Lead", "CountryDirector", "Admin"} {
		if !canReviewRole(allowed) {
			t.Errorf("%q should be allowed to review", allowed)
		}
	}
	for _, denied := range []string{"CCEO", "Accountant", "PartnerAdmin", "ImpactAssessment", ""} {
		if canReviewRole(denied) {
			t.Errorf("%q should not be allowed to review", denied)
		}
	}
}

func TestReturnRejectsBlankReasonBeforeOpeningTransaction(t *testing.T) {
	svc := NewReviewService(nil, nil)
	_, err := svc.Return(context.Background(), auth.Principal{Account: auth.Account{ActiveRole: "Program Lead"}}, "act1", "   ")
	var refusal *ReviewRefusal
	if !errors.As(err, &refusal) || refusal.Forbidden {
		t.Fatalf("expected non-forbidden refusal, got %v", err)
	}
}

func TestExportRejectsUnauthorizedRole(t *testing.T) {
	svc := NewReviewService(nil, nil)
	_, _, err := svc.ExportCompletedVisitsCSV(context.Background(), auth.Principal{Account: auth.Account{ActiveRole: "PartnerFieldOfficer"}})
	var refusal *ReviewRefusal
	if !errors.As(err, &refusal) || !refusal.Forbidden {
		t.Fatalf("expected forbidden refusal, got %v", err)
	}
}
