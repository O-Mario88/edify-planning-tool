package activities

import (
	"errors"
	"testing"
)

func TestSubmitForReviewRefusesInTheExistingWords(t *testing.T) {
	tests := []struct {
		status, salesforceID, want string
	}{
		{"scheduled", "SV-1", "Activity is not ready to be submitted for review."},
		{"submitted_to_pl", "SV-1", "Activity is not ready to be submitted for review."},
		{"completed", "", "Enter the Salesforce Activity ID before submitting."},
		{"returned_by_pl", "", "Enter the Salesforce Activity ID before submitting."},
		{"returned_by_pl", "SV-1", ""},
		{"returned_by_ia", "SV-1", ""},
		{"completion_started", "SV-1", ""},
		{"completed", "SV-1", ""},
	}
	for _, tt := range tests {
		if got := submitRefusal(tt.status, tt.salesforceID); got != tt.want {
			t.Fatalf("%s/%q: got %q", tt.status, tt.salesforceID, got)
		}
	}
}

func TestTheSubmitFunctionsAnswerIsReadBack(t *testing.T) {
	if err := submitAnswer(""); err != nil {
		t.Fatalf("handed in: %v", err)
	}
	var refusal *Refusal
	if err := submitAnswer("not_ready"); !errors.As(err, &refusal) || refusal.Message != "Activity is not ready to be submitted for review." {
		t.Fatalf("not ready: %v", err)
	}
	if err := submitAnswer("no_id"); !errors.As(err, &refusal) || refusal.Message != "Enter the Salesforce Activity ID before submitting." {
		t.Fatalf("no id: %v", err)
	}
	if err := submitAnswer("changed"); !errors.Is(err, ErrHandOn) {
		t.Fatalf("changed under the lock is handed on: %v", err)
	}
}
