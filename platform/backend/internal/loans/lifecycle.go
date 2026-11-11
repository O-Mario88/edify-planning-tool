package loans

import "fmt"

// Application statuses: the brief's lifecycle. Delivery to the lender has
// statuses of its own (Delivery*), never folded into these.
const (
	StatusSubmitted            = "submitted"
	StatusAwaitingReceipt      = "awaiting_lender_receipt"
	StatusReceived             = "received_by_lender"
	StatusUnderReview          = "under_review"
	StatusInformationRequested = "information_requested"
	StatusApproved             = "approved"
	StatusDeclined             = "declined"
	StatusDisbursed            = "disbursed"
	StatusClosed               = "closed"
	StatusWithdrawn            = "withdrawn"
)

// Statuses in lifecycle order.
var Statuses = []string{
	StatusSubmitted, StatusAwaitingReceipt, StatusReceived, StatusUnderReview,
	StatusInformationRequested, StatusApproved, StatusDeclined, StatusDisbursed,
	StatusClosed, StatusWithdrawn,
}

var statusLabels = map[string]string{
	StatusSubmitted:            "Submitted",
	StatusAwaitingReceipt:      "Awaiting Lender Receipt",
	StatusReceived:             "Received by Lender",
	StatusUnderReview:          "Under Review",
	StatusInformationRequested: "Additional Information Requested",
	StatusApproved:             "Approved",
	StatusDeclined:             "Declined",
	StatusDisbursed:            "Disbursed",
	StatusClosed:               "Closed",
	StatusWithdrawn:            "Withdrawn",
}

// StatusLabel is a status as people read it.
func StatusLabel(status string) string {
	if label, ok := statusLabels[status]; ok {
		return label
	}
	return status
}

// Delivery statuses: how far the lender's notification got.
const (
	DeliveryQueued = "queued"
	DeliverySent   = "sent"
	DeliveryFailed = "failed"
	DeliveryOpened = "opened_by_lender"
)

var deliveryLabels = map[string]string{
	DeliveryQueued: "Waiting to be sent",
	DeliverySent:   "Notification sent",
	DeliveryFailed: "Delivery failed",
	DeliveryOpened: "Opened by lender",
}

// DeliveryLabel is a delivery status as people read it.
func DeliveryLabel(status string) string {
	if label, ok := deliveryLabels[status]; ok {
		return label
	}
	return status
}

// IsOpen says whether an application is still in progress.
func IsOpen(status string) bool {
	switch status {
	case StatusDeclined, StatusDisbursed, StatusClosed, StatusWithdrawn:
		return false
	}
	return true
}

// Who acts on an application.
const (
	ActorLender = "lender"
	ActorStaff  = "staff"
	// ActorStaffCorrection is staff recording what the lender decided, with
	// evidence, when the lender cannot record it themselves.
	ActorStaffCorrection = "staff_correction"
)

// Actions on an application.
const (
	ActionAcknowledge        = "acknowledge"
	ActionStartReview        = "start_review"
	ActionRequestInformation = "request_information"
	ActionApprove            = "approve"
	ActionDecline            = "decline"
	ActionDisburse           = "disburse"
	ActionClose              = "close"
	ActionWithdraw           = "withdraw"
)

var beforeDecision = []string{
	StatusSubmitted, StatusAwaitingReceipt, StatusReceived, StatusUnderReview, StatusInformationRequested,
}

// lenderMoves are the lender-controlled stages (brief §9: acknowledge
// receipt, request information, update stages, record outcomes, confirm
// disbursement).
var lenderMoves = map[string]struct {
	to   string
	from []string
}{
	ActionAcknowledge:        {StatusReceived, []string{StatusSubmitted, StatusAwaitingReceipt}},
	ActionStartReview:        {StatusUnderReview, []string{StatusSubmitted, StatusAwaitingReceipt, StatusReceived, StatusInformationRequested}},
	ActionRequestInformation: {StatusInformationRequested, beforeDecision},
	ActionApprove:            {StatusApproved, beforeDecision},
	ActionDecline:            {StatusDeclined, append(append([]string{}, beforeDecision...), StatusApproved)},
	ActionDisburse:           {StatusDisbursed, []string{StatusApproved}},
	ActionClose:              {StatusClosed, []string{StatusDisbursed, StatusDeclined}},
}

// NextStatus is the status action moves from to, or an error saying why it
// may not. Staff never decide: they withdraw (on the school's request) or
// close, and record a lender's decision only as a correction.
func NextStatus(from, action, actor string) (string, error) {
	if from == StatusClosed || from == StatusWithdrawn {
		return "", fmt.Errorf("a %s application cannot change", StatusLabel(from))
	}
	switch actor {
	case ActorLender, ActorStaffCorrection:
		move, ok := lenderMoves[action]
		if !ok {
			return "", fmt.Errorf("%s is not something a lender records", action)
		}
		for _, allowed := range move.from {
			if allowed == from {
				return move.to, nil
			}
		}
		return "", fmt.Errorf("an application that is %s cannot move to %s", StatusLabel(from), StatusLabel(move.to))
	case ActorStaff:
		switch action {
		case ActionWithdraw:
			if from == StatusDisbursed || from == StatusDeclined {
				return "", fmt.Errorf("a %s application cannot be withdrawn", StatusLabel(from))
			}
			return StatusWithdrawn, nil
		case ActionClose:
			if from == StatusDisbursed || from == StatusDeclined {
				return StatusClosed, nil
			}
			return "", fmt.Errorf("only a disbursed or declined application can be closed")
		}
		return "", fmt.Errorf("only the lender, or a correction with the lender's evidence, records %s", action)
	}
	return "", fmt.Errorf("unknown actor %q", actor)
}
