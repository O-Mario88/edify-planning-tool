package activities

import (
	"errors"
	"testing"
)

// confirm_reimbursement_receipt's refusals, word for word.
func TestReimbursementRefusalsAreTheExistingWords(t *testing.T) {
	for answer, want := range map[string]string{
		"gone":         "Advance request not found.",
		"not_owner":    "Only the responsible user can confirm reimbursement receipt.",
		"nothing":      "Nothing to confirm — no disbursed reimbursement is awaiting receipt confirmation.",
		"unreconciled": "Cannot confirm — accounted amount does not reconcile with disbursed minus returned plus reimbursed. Critical finance error.",
	} {
		var r *Refusal
		if err := reimbursementRefusal(answer); !errors.As(err, &r) || r.Message != want {
			t.Fatalf("%s: %v", answer, err)
		}
	}
	if reimbursementRefusal("ok") != nil {
		t.Fatal("ok is no refusal")
	}
}

// int(data.get("amount", reimbursed) or 0): an empty amount is nought; no
// amount at all is the reimbursed amount.
func TestTheAmountReceivedIsReadAsTheServiceReadsIt(t *testing.T) {
	if got, err := reimbursementAmount("", true); err != nil || got == nil || *got != 0 {
		t.Fatalf("empty: %v %v", got, err)
	}
	if got, err := reimbursementAmount(" 15000 ", true); err != nil || got == nil || *got != 15000 {
		t.Fatalf("given: %v %v", got, err)
	}
	if got, err := reimbursementAmount("", false); err != nil || got != nil {
		t.Fatalf("absent: %v %v", got, err)
	}
	if _, err := reimbursementAmount("12.5", true); err == nil {
		t.Fatal("a fraction is refused")
	}
}
