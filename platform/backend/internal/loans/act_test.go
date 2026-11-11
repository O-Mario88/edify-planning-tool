package loans

import (
	"errors"
	"testing"
	"time"
)

func TestDisbursementNeedsItsOwnAmountDateAndReference(t *testing.T) {
	submitted := time.Date(2026, 11, 1, 9, 0, 0, 0, kampala)
	today := time.Date(2026, 11, 11, 0, 0, 0, 0, kampala)
	lender := Actor{Kind: ActorLender}
	good := ActDetails{DisbursedAmount: 38_000_000, DisbursementDate: today, DisbursementReference: "LN-1"}
	if err := checkDetails(ActionDisburse, lender, good, submitted, today); err != nil {
		t.Fatalf("a complete disbursement was refused: %v", err)
	}
	for name, details := range map[string]ActDetails{
		"no amount":       {DisbursementDate: today, DisbursementReference: "LN-1"},
		"no date":         {DisbursedAmount: 1, DisbursementReference: "LN-1"},
		"a future date":   {DisbursedAmount: 1, DisbursementDate: today.AddDate(0, 0, 1), DisbursementReference: "LN-1"},
		"before applying": {DisbursedAmount: 1, DisbursementDate: submitted.AddDate(0, 0, -1), DisbursementReference: "LN-1"},
		"no reference":    {DisbursedAmount: 1, DisbursementDate: today},
	} {
		var field *FieldError
		if err := checkDetails(ActionDisburse, lender, details, submitted, today); !errors.As(err, &field) {
			t.Errorf("%s was accepted", name)
		}
	}
}

func TestApprovalNeedsTheApprovedAmountNotTheRequestedOne(t *testing.T) {
	now := time.Now()
	if err := checkDetails(ActionApprove, Actor{Kind: ActorLender}, ActDetails{}, now, now); err == nil {
		t.Fatal("an approval without its amount was accepted")
	}
}

func TestACorrectionNeedsEvidenceAndAReason(t *testing.T) {
	now := time.Now()
	correction := Actor{Kind: ActorStaffCorrection}
	if err := checkDetails(ActionApprove, correction, ActDetails{ApprovedAmount: 5, Note: "lender emailed"}, now, now); err == nil {
		t.Fatal("a correction without evidence was accepted")
	}
	if err := checkDetails(ActionApprove, correction, ActDetails{ApprovedAmount: 5, Note: "lender emailed", Evidence: "email of 3 Nov"}, now, now); err != nil {
		t.Fatalf("a complete correction was refused: %v", err)
	}
}

func TestDeclineAndInformationRequestsNeedWords(t *testing.T) {
	now := time.Now()
	for _, action := range []string{ActionDecline, ActionRequestInformation, ActionWithdraw} {
		if err := checkDetails(action, Actor{Kind: ActorLender}, ActDetails{Note: "  "}, now, now); err == nil {
			t.Errorf("%s without a note was accepted", action)
		}
	}
}
