package plreview

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestReturnRejectsBlankReasonBeforeOpeningTransaction(t *testing.T) {
	svc := NewReviewService(nil, nil)
	_, err := svc.Return(context.Background(), auth.Principal{Account: auth.Account{ActiveRole: "Program Lead"}}, "act1", nil, "   ")
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
