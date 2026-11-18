package partneroversight

import (
	"slices"
	"strings"
	"time"
)

// The stages of partner work (partner_oversight_service STAGE_*).
const (
	stageAwaiting  = "awaiting_schedule"
	stageScheduled = "scheduled"
	stageReturned  = "returned"
)

// item is partner_oversight_service.PartnerOversightItem: one piece of work
// handed to a Partner (a hand-over, enriched by the activity the Partner's
// scheduling created), or a Partner activity no hand-over points at.
type item struct {
	stage        string
	assignmentID string
	activityID   string

	schoolID, schoolCode, schoolName, schoolType, district string
	clusterID, clusterName, schoolClusterName              string
	projectID, projectName                                 string
	partnerID, partnerName                                 string
	cceoID, cceoName, plID, plName                         string

	activityType                                  string
	trainingName, purposeLabel, interventionLabel string
	// targetIntervention is intervention_or_general's code: the focus the
	// work names (project work, the only kind that could read General, is
	// handed on).
	targetIntervention                               string
	assignmentDate, scheduledDate, submittedToIA     *time.Time
	quarter                                          string
	assignmentStatus, activityStatus, evidenceStatus string
	salesforceRecorded                               bool
	iaStatus, paymentStatus                          string
	returnReasonCategory, returnReason               string
	resolution, resolutionLabel                      string
	fieldOfficer                                     string
	rescheduleCount                                  int
	plannedCost                                      *int64
	partnerHasDated                                  bool

	// The completion columns (completion_columns.annotate).
	salesforceID, evidenceLabel string
	salesforceOK, evidenceOK    bool
	isComplete                  bool
	completionGap               string
	completedOn                 *time.Time

	risks           []string
	withdrawalLabel string
	// act is the activity behind the work, for the completion columns.
	act *activity

	// The Core Schools table (annotate_core_support): the package slot the
	// work holds ("V2", "T1"), what the Partner is paid for it before they
	// date it, and the hand-over's support type and purpose that decide the
	// rate.
	// canReview is whether the reader may Verify & Confirm or Return the
	// work waiting for IA verification; reviewIsSSA that it is SSA Support,
	// confirmed in its own drawer.
	canReview, reviewIsSSA bool
	// projectLocked is Special Project work the reader may not withdraw or
	// decide (its Project Coordinator's).
	projectLocked bool

	coreSlotLabel            string
	partnerRate              *int64
	supportType, purposeCode string
}

// showsComplete is complete work whose status is a completed one.
func (i *item) showsComplete() bool {
	return i.isComplete && in(rules.Work.Completion.CompletedWork, i.activityStatus)
}

// displayCost is the Core Schools table's Cost: the scheduled work's price,
// nothing for work taken back, else the Partner's rate.
func (i *item) displayCost() *int64 {
	if i.isScheduled() && i.plannedCost != nil && *i.plannedCost != 0 {
		return i.plannedCost
	}
	if i.isReturned() {
		return nil
	}
	return i.partnerRate
}

// coreTraining is annotate_core_support's test: an in-school training is
// priced as a Partner school visit whatever the school.
func (i *item) coreTraining() bool {
	return in(rules.Work.TrainingTypes, i.activityType) || i.supportType == "Training" || i.purposeCode == "in_school_training"
}

func in(list []string, v string) bool { return slices.Contains(list, v) }

func (i *item) isScheduled() bool { return i.stage == stageScheduled }
func (i *item) isReturned() bool  { return i.stage == stageReturned }

// awaitsStaffDecision is a hand-back nobody has decided on.
func (i *item) awaitsStaffDecision() bool { return i.stage == stageReturned && i.resolution == "" }

func (i *item) scheduleStatus() string {
	switch {
	case i.stage == stageReturned:
		return "Returned to Staff"
	case i.stage == stageAwaiting:
		return "Awaiting Schedule"
	case i.rescheduleCount > 0:
		return "Rescheduled"
	}
	return "Scheduled"
}

func (i *item) executionStatus() string {
	w := rules.Work
	switch {
	case !i.isScheduled():
		return "—"
	case in(w.NotStarted, i.activityStatus):
		return "Not Started"
	case in(w.InProgress, i.activityStatus), in(w.ReturnedToPartner, i.activityStatus),
		i.activityStatus == "evidence_uploaded", i.activityStatus == "evidence_accepted":
		return "In Progress"
	}
	return "Evidence Submitted"
}

func (i *item) iaStatusLabel() string {
	w := rules.Work
	switch {
	case in(w.ReturnedToPartner, i.activityStatus) || i.iaStatus == "returned":
		return "Returned"
	case i.iaStatus == "confirmed" || i.activityStatus == "ia_verified" || i.activityStatus == "accountant_confirmed":
		return "Verified"
	case i.executionStatus() == "Evidence Submitted":
		return "Pending"
	}
	return "—"
}

func (i *item) salesforceLabel() string {
	if !i.isScheduled() || i.executionStatus() != "Evidence Submitted" {
		return "—"
	}
	if i.salesforceRecorded {
		return "Confirmed"
	}
	return "Pending"
}

func (i *item) paymentLabel() string {
	w := rules.Work
	switch {
	case i.iaStatusLabel() != "Verified":
		return "Not Eligible"
	case in(w.Paid, i.paymentStatus):
		return "Paid"
	case in(w.PaymentProcessing, i.paymentStatus):
		return "Processing"
	}
	return "Awaiting Payment"
}

// isOverdue is the row's Overdue chip: scheduled work whose day has passed
// and that has not started (a hand-over carries no schedule-by date since
// 2026-10-05, so waiting work is never overdue here).
func (i *item) isOverdue(today time.Time) bool {
	return i.isScheduled() && i.scheduledDate != nil && i.scheduledDate.Before(today) &&
		i.executionStatus() == "Not Started"
}

// deliveryPhase is which of the page's columns the work belongs under.
func (i *item) deliveryPhase() string {
	w := rules.Work
	switch {
	case i.stage == stageReturned:
		return "returned"
	case i.stage == stageAwaiting:
		return "awaiting_schedule"
	case in(w.Complete, i.activityStatus):
		return "completed"
	case in(w.AwaitingIA, i.activityStatus), in(w.EvidenceReview, i.activityStatus):
		return "verification"
	case in(w.InProgress, i.activityStatus):
		return "in_progress"
	}
	return "scheduled"
}

// statusLabel is the Status column in words.
func (i *item) statusLabel() string {
	if i.awaitsStaffDecision() {
		return i.scheduleStatus()
	}
	return pyTitle(strings.ReplaceAll(i.deliveryPhase(), "_", " "))
}

// activityDate is the Activity date column: the Partner's day, none before.
func (i *item) activityDate() *time.Time {
	if i.stage != stageScheduled {
		return nil
	}
	return i.scheduledDate
}

func (i *item) isCoreSchoolWork() bool {
	return i.assignmentID != "" && i.schoolID != "" && i.schoolType == "core"
}

// withdrawalKind is withdrawal_service.resolve_kind over the item.
func (i *item) withdrawalKind() string {
	w := rules.Work.Withdrawal
	if i.assignmentStatus == rules.ReturnedToStaff {
		return "blocked"
	}
	if i.activityID == "" {
		return "withdraw_unscheduled"
	}
	status := i.activityStatus
	switch {
	case in(w.Paid, status) || in(w.Paid, i.paymentStatus), in(w.Closed, status):
		return "blocked"
	case in(w.IACleared, status):
		return "payment_hold"
	case in(w.Evidence, status) || (i.evidenceStatus != "" && i.evidenceStatus != "none"):
		return "quality_review"
	case in(w.InProgress, status):
		return "suspend_in_progress"
	case in(w.NotStarted, status):
		return "recall_scheduled"
	}
	return "blocked"
}

// withdrawalLabelOf is withdrawal_service.action_label.
func withdrawalLabelOf(kind string, partnerHasDated bool) string {
	w := rules.Work.Withdrawal
	label, known := w.Labels[kind]
	if kind == "blocked" || !known {
		return ""
	}
	if kind == "recall_scheduled" && !partnerHasDated {
		return w.WithdrawFromPartner
	}
	return label
}

// workTab is work_tab_of: which tab a Partner activity sits in.
func (i *item) workTab() string {
	w := rules.Work
	switch {
	case i.clusterID != "" && i.schoolID == "":
		return "clusters"
	case in(w.ClusterMeetingTypes, i.activityType):
		return "clusters"
	case in(w.TrainingTypes, i.activityType):
		return "trainings"
	}
	return "visits"
}

// matches is filter_workspace's status test: the row's delivery phase.
func (i *item) matches(status string) bool { return status == "" || i.deliveryPhase() == status }

// pyTitle is Python's str.title: each run of letters starts capital and
// continues small.
func pyTitle(s string) string {
	var b strings.Builder
	prevLetter := false
	for _, r := range s {
		isLetter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case isLetter && !prevLetter:
			b.WriteString(strings.ToUpper(string(r)))
		case isLetter:
			b.WriteString(strings.ToLower(string(r)))
		default:
			b.WriteRune(r)
		}
		prevLetter = isLetter
	}
	return b.String()
}
