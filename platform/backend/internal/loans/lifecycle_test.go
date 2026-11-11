package loans

import "testing"

func TestTheLenderMovesAnApplicationThroughItsStages(t *testing.T) {
	steps := []struct {
		from   string
		action string
		to     string
	}{
		{StatusAwaitingReceipt, ActionAcknowledge, StatusReceived},
		{StatusReceived, ActionStartReview, StatusUnderReview},
		{StatusUnderReview, ActionRequestInformation, StatusInformationRequested},
		{StatusInformationRequested, ActionStartReview, StatusUnderReview},
		{StatusUnderReview, ActionApprove, StatusApproved},
		{StatusApproved, ActionDisburse, StatusDisbursed},
		{StatusDisbursed, ActionClose, StatusClosed},
	}
	for _, step := range steps {
		to, err := NextStatus(step.from, step.action, ActorLender)
		if err != nil || to != step.to {
			t.Errorf("%s --%s--> %q, %v; want %s", step.from, step.action, to, err, step.to)
		}
	}
}

func TestALenderMayActBeforeAcknowledging(t *testing.T) {
	for _, action := range []string{ActionStartReview, ActionApprove, ActionDecline, ActionRequestInformation} {
		if _, err := NextStatus(StatusAwaitingReceipt, action, ActorLender); err != nil {
			t.Errorf("%s from awaiting receipt: %v", action, err)
		}
	}
}

func TestDisbursementOnlyFollowsApproval(t *testing.T) {
	for _, from := range []string{StatusSubmitted, StatusAwaitingReceipt, StatusReceived, StatusUnderReview, StatusDeclined} {
		if _, err := NextStatus(from, ActionDisburse, ActorLender); err == nil {
			t.Errorf("disbursed straight from %s", from)
		}
	}
}

func TestAFinishedApplicationDoesNotMove(t *testing.T) {
	for _, from := range []string{StatusClosed, StatusWithdrawn} {
		for _, action := range []string{ActionAcknowledge, ActionApprove, ActionWithdraw, ActionDisburse} {
			if _, err := NextStatus(from, action, ActorLender); err == nil {
				t.Errorf("%s moved by %s", from, action)
			}
			if _, err := NextStatus(from, action, ActorStaff); err == nil {
				t.Errorf("%s moved by staff %s", from, action)
			}
		}
	}
}

func TestStaffWithdrawOpenApplicationsOnly(t *testing.T) {
	if to, err := NextStatus(StatusUnderReview, ActionWithdraw, ActorStaff); err != nil || to != StatusWithdrawn {
		t.Fatalf("withdraw: %q %v", to, err)
	}
	for _, from := range []string{StatusDisbursed, StatusDeclined} {
		if _, err := NextStatus(from, ActionWithdraw, ActorStaff); err == nil {
			t.Errorf("withdrew a %s application", from)
		}
	}
}

func TestOnlyTheLenderOrACorrectionDecides(t *testing.T) {
	// Staff record a decision only through a correction, which needs evidence
	// (checked by the service); a plain staff action never decides.
	if _, err := NextStatus(StatusUnderReview, ActionApprove, ActorStaff); err == nil {
		t.Fatal("staff approved without a correction")
	}
	if to, err := NextStatus(StatusUnderReview, ActionApprove, ActorStaffCorrection); err != nil || to != StatusApproved {
		t.Fatalf("correction: %q %v", to, err)
	}
	if _, err := NextStatus(StatusUnderReview, ActionWithdraw, ActorLender); err == nil {
		t.Fatal("a lender withdrew the school's application")
	}
}

func TestEveryStatusHasALabelAndIsOpenOrFinished(t *testing.T) {
	for _, status := range Statuses {
		if StatusLabel(status) == "" || StatusLabel(status) == status {
			t.Errorf("%s has no label", status)
		}
	}
	if IsOpen(StatusDisbursed) || IsOpen(StatusClosed) || IsOpen(StatusDeclined) || !IsOpen(StatusApproved) {
		t.Fatal("open/finished sets are wrong")
	}
}
