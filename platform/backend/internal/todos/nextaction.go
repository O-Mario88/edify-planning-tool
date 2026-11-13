package todos

import "time"

// activity is what compute_next_action reads of an activity.
type activity struct {
	ID, Status, DeliveryType, EvidenceStatus string
	PlannedDate                              *time.Time // a day, at midnight UTC
	SalesforceID, ActivityType               string
	Teachers, Leaders                        int
	HasSchool                                bool
	SchoolSSAStatus                          string
	IAVerification, Payment                  string
	Advances                                 []advance // cost line by cost line, each line's newest first
}

// advance is what compute_next_action reads of an advance request.
type advance struct {
	Status                     string
	ReceiptConfirmed, NetSuite bool
}

// nextAction is compute_next_action's answer.
type nextAction struct {
	Text, Action, URL string
}

// workedStatuses is my_plan.services._WORKED_STATUSES.
var workedStatuses = []string{"completed", "completion_started", "in_progress", "evidence_uploaded",
	"evidence_accepted", "salesforce_id_required"}

// submitNeedsParticipants is SUBMIT_NEEDS_PARTICIPANTS_TYPES.
var submitNeedsParticipants = []string{"training", "cluster_training", "cluster_meeting", "core_training"}

// ssaTypes are the activity types that expect an SSA (branch 6).
var ssaTypes = []string{"baseline_ssa_visit", "school_visit_ssa_collection", "partner_ssa_collection",
	"cluster_training_ssa_collection"}

// computeNextAction is my_plan.services.compute_next_action, branch by
// branch; testdata/next_action_cases.json holds its answers over a grid of
// activities, which TestNextActionIsTheExistingOne compares.
func computeNextAction(a activity, today time.Time) nextAction {
	view := nextAction{"View Details", "view", "/my-plan/" + a.ID}
	status := func(text, desc string) nextAction { return nextAction{text, "view_status", "/my-plan/" + a.ID} }
	partner := a.DeliveryType == "partner"
	plannedToday := a.PlannedDate != nil && a.PlannedDate.Equal(today)
	if a.Status == "awaiting_owner_approval" {
		return nextAction{"Waiting for owner approval", "await_owner", "/planning/visit-requests"}
	}
	if contains([]string{"returned", "returned_by_pl", "returned_by_ia"}, a.Status) {
		if partner {
			return nextAction{"Correct Returned Evidence", "fix", "/partner/activities/" + a.ID + "/evidence"}
		}
		return nextAction{"Fix and Resubmit", "fix", "/activities/" + a.ID + "/complete"}
	}
	if partner && a.EvidenceStatus == "uploaded" && !contains([]string{"closed", "cancelled", "rejected",
		"ia_verified", "returned_by_ia", "awaiting_ia_verification"}, a.Status) {
		return nextAction{"Submit Evidence to IA", "submit_evidence", "/partner/activities/" + a.ID + "/evidence"}
	}
	if contains([]string{"scheduled", "rescheduled", "partner_scheduled"}, a.Status) && plannedToday {
		if partner {
			return nextAction{"Start", "start", "/partner/activities/" + a.ID + "/evidence"}
		}
		return nextAction{"Start", "start", "/activities/" + a.ID + "/start"}
	}
	if a.Status == "partner_scheduled" && partner && a.PlannedDate != nil && a.PlannedDate.After(today) {
		return nextAction{"Prepare", "prepare", "/my-plan/" + a.ID}
	}
	if a.Status == "in_progress" {
		return nextAction{"Complete Activity", "complete", "/activities/" + a.ID + "/complete"}
	}
	worked := contains(workedStatuses, a.Status)
	if partner && a.EvidenceStatus == "none" && worked {
		return nextAction{"Upload Evidence", "evidence", "/activities/" + a.ID + "/evidence"}
	}
	if !partner && a.EvidenceStatus == "none" && worked && a.Status != "completed" {
		return nextAction{"Complete Activity", "complete", "/activities/" + a.ID + "/complete"}
	}
	formStepMet := a.EvidenceStatus == "uploaded" || (!partner && a.EvidenceStatus == "none")
	if worked && formStepMet && a.SalesforceID == "" {
		return nextAction{"Enter Activity SF ID", "sf_id", "/activities/" + a.ID + "/salesforce-id"}
	}
	if worked && formStepMet && a.SalesforceID != "" {
		if !contains(submitNeedsParticipants, a.ActivityType) || a.Teachers+a.Leaders > 0 {
			return nextAction{"Submit", "submit", "/activities/" + a.ID + "/submit"}
		}
	}
	if contains(ssaTypes, a.ActivityType) && a.HasSchool && a.SchoolSSAStatus != "done" {
		return nextAction{"Upload SSA", "ssa", "/activities/" + a.ID + "/complete"}
	}
	if a.Status == "awaiting_ia_verification" && a.IAVerification == "pending" {
		return status("View Status", "")
	}
	if a.Status == "ia_verified" && a.IAVerification == "confirmed" &&
		contains([]string{"none", "pending_ia", "ia_confirmed"}, a.Payment) {
		return status("View Accounts Status", "")
	}
	for _, adv := range a.Advances {
		if adv.Status == "reimbursement_disbursed" && !adv.ReceiptConfirmed {
			return nextAction{"Confirm Reimbursement Receipt", "reimbursement_receipt",
				"/my-plan/" + a.ID + "/confirm-reimbursement-receipt"}
		}
	}
	for _, adv := range a.Advances {
		if adv.Status == "disbursed" && !adv.NetSuite {
			return nextAction{"Submit Accountability", "accountability", "/my-plan/" + a.ID + "/accountability"}
		}
	}
	for _, adv := range a.Advances {
		if adv.Status == "accountability_pending" {
			return status("Awaiting Finance Clearance", "")
		}
	}
	for _, adv := range a.Advances {
		switch adv.Status {
		case "accountability_pl_pending":
			return status("Awaiting PL Accountability Approval", "")
		case "reimbursement_pl_pending":
			return status("Awaiting PL Claim Approval", "")
		case "reimbursement_submitted":
			return status("Awaiting Reimbursement", "")
		}
	}
	return view
}

// actPriority is todo_service._act_priority.
func actPriority(a activity, action string, today time.Time) string {
	switch action {
	case "accountability", "reimbursement_receipt":
		return "critical"
	case "submit_evidence", "fix", "evidence", "sf_id", "complete":
		return "high"
	case "start":
		if a.PlannedDate != nil && a.PlannedDate.Equal(today) {
			return "high"
		}
		return "medium"
	case "ssa", "submit":
		return "medium"
	}
	return "low"
}

// actStatus is todo_service._act_status's key (its label and tone are not
// drawn).
func actStatus(a activity, action string, today time.Time) string {
	switch {
	case contains([]string{"returned", "returned_by_pl", "returned_by_ia"}, a.Status):
		return "returned"
	case contains(rules.Waiting, action):
		return "blocked"
	case a.PlannedDate != nil && a.PlannedDate.Before(today):
		return "overdue"
	case a.PlannedDate != nil && a.PlannedDate.Equal(today):
		return "due_today"
	}
	return "waiting_me"
}
