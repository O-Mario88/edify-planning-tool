package workplan

import (
	"net/url"
	"strconv"
	"strings"
	"time"
)

// group is _activity_group: "school" or "non_school".
func group(a *activity) string {
	if a.planningSource == "manual_work_plan" || a.activityType == "programme_event" || a.activityType == "field_event" {
		return "non_school"
	}
	if isSet(a.schoolPK) || isSet(a.clusterID) || in(rules.VisitTypes, a.activityType) ||
		in(rules.TrainingTypes, a.activityType) || in(rules.ClusterMeetingTypes, a.activityType) {
		return "school"
	}
	return "non_school"
}

func typeDisplay(a *activity) string { return display("activity_type", a.activityType) }

// bucketLabel is _summary_bucket_label: one summary line per executor and
// type, a non-school activity by its planned name, a pair's free half on a
// line of its own.
func bucketLabel(a *activity, costNote string) string {
	executor := "Staff"
	if a.delivery == "partner" {
		executor = "Partner"
	}
	label := typeDisplay(a)
	if group(a) == "non_school" {
		switch {
		case isSet(a.nameSnapshot):
			label = *a.nameSnapshot
		case isSet(a.itemID):
			label = str(a.itemName)
		}
	} else {
		label += rules.PairBucketSuffix[costNote]
	}
	return executor + " " + label
}

// kind is work_plan_tables._kind: meeting, in_school, training, visit or
// other.
func kind(a *activity, g string) string {
	switch {
	case g == "non_school":
		return "other"
	case in(rules.ClusterMeetingTypes, a.activityType):
		return "meeting"
	case a.activityType == "in_school_training":
		return "in_school"
	case in(rules.TrainingTypes, a.activityType):
		return "training"
	case in(rules.VisitTypes, a.activityType):
		return "visit"
	}
	return "other"
}

// activityWord is work_plan_tables.activity_word.
func activityWord(a *activity, g string) string {
	switch kind(a, g) {
	case "visit":
		return "Visit"
	case "in_school", "training":
		return "Training"
	case "meeting":
		return "Meeting"
	}
	word := typeDisplay(a)
	if isSet(a.programmeType) {
		word = display("programme_activity_type", *a.programmeType)
	}
	if word == "" {
		return "Activity"
	}
	return word
}

// activityPurpose is work_plan_tables.activity_purpose.
func activityPurpose(a *activity, g string) string {
	t := rules.Table
	switch kind(a, g) {
	case "in_school":
		return t.InSchoolTraining
	case "training":
		return t.GroupTraining
	case "meeting":
		return t.ClusterMeeting
	case "visit":
		if str(a.purposeType) == t.CompanionVisitPurpose {
			return t.InSchoolTraining
		}
		if label := rules.VisitPurposeLabels[str(a.purposeType)]; label != "" {
			return label
		}
		return typeDisplay(a)
	}
	if isSet(a.nameSnapshot) {
		return *a.nameSnapshot
	}
	if v := display("programme_activity_type", str(a.programmeType)); v != "" {
		return v
	}
	return typeDisplay(a)
}

// titleCase is str.title(): each run of letters capitalised after a
// non-letter, the rest lowered.
func titleCase(s string) string {
	var b strings.Builder
	prev := false
	for _, r := range s {
		letter := isCased(r)
		switch {
		case letter && !prev:
			b.WriteString(strings.ToTitle(string(r)))
		case letter:
			b.WriteString(strings.ToLower(string(r)))
		default:
			b.WriteRune(r)
		}
		prev = letter
	}
	return b.String()
}

func isCased(r rune) bool {
	return strings.ToLower(string(r)) != strings.ToUpper(string(r))
}

// deliveryMode is work_plan_tables.delivery_mode.
func deliveryMode(a *activity, g string) string {
	t := rules.Table
	switch kind(a, g) {
	case "in_school":
		return t.InSchoolTraining
	case "training":
		if str(a.deliveryMode) == "online" {
			return t.OnlineTrainingLabel
		}
		return t.GroupTraining
	case "meeting":
		return t.ClusterMeeting
	case "visit":
		return t.SchoolVisit
	}
	if isSet(a.deliveryMode) {
		return display("programme_delivery_mode", *a.deliveryMode)
	}
	if v := titleCase(strings.ReplaceAll(str(a.deliveryMethod), "_", " ")); v != "" {
		return v
	}
	return t.NotRecorded
}

// previousScore is work_plan_tables.previous_ssa_score.
func previousScore(a *activity) string {
	if a.sourceScore == nil {
		return rules.Table.NotRecorded
	}
	return strconv.FormatFloat(*a.sourceScore, 'f', 1, 64)
}

// dated is `getattr(activity, "planned_date", True) or scheduled_date`.
func dated(a *activity) bool { return a.planned != nil || a.scheduled != nil }

// deliveryStatus is work_plan_tables.delivery_status's words.
func deliveryStatus(a *activity) string {
	switch {
	case a.status == "cancelled":
		return "Cancelled"
	case in(rules.CompletedWorkStatuses, a.status):
		return "Complete"
	case dated(a):
		return "Scheduled"
	}
	return "Planned"
}

// districtName is detail_fields' district: the school's, else the
// cluster's, else the event's.
func districtName(a *activity) string {
	if isSet(a.schoolPK) && a.schoolDistrict != nil {
		return *a.schoolDistrict
	}
	if isSet(a.clusterID) && a.clusterDistrict != nil {
		return *a.clusterDistrict
	}
	return str(a.eventDistrict)
}

// focusIntervention is the row's SSA Intervention: General for non-school
// work and for school work under a project no SSA measures, else the
// intervention planned.
func focusIntervention(a *activity, g string, outside map[string]bool) string {
	switch {
	case g == "non_school":
		return rules.Table.General
	case isSet(a.focus):
		return display("focus_intervention", *a.focus)
	case isSet(a.projectID) && outside[*a.projectID]:
		return rules.Table.General
	}
	return ""
}

// verdict is plan_alignment.verdict_display's label and the planner's
// reason, as the compact verdict shows them.
func verdictLabel(a *activity) string {
	for _, pair := range rules.SSAAlignmentLabels {
		if pair[0] == a.alignment {
			return pair[1]
		}
	}
	return a.alignment
}

// dateLabel is _date_label.
func dateLabel(start, end *time.Time) string {
	if start == nil {
		return "Not dated"
	}
	s := *start
	if end != nil && !end.Equal(s) {
		e := *end
		switch {
		case e.Year() == s.Year() && e.Month() == s.Month():
			return strconv.Itoa(s.Day()) + "–" + strconv.Itoa(e.Day()) + " " + monthNames[s.Month()] + " " + strconv.Itoa(s.Year())
		case e.Year() == s.Year():
			return strconv.Itoa(s.Day()) + " " + monthNames[s.Month()] + " – " + strconv.Itoa(e.Day()) + " " + monthNames[e.Month()] + " " + strconv.Itoa(e.Year())
		}
		return strconv.Itoa(s.Day()) + " " + monthNames[s.Month()] + " " + strconv.Itoa(s.Year()) + " – " +
			strconv.Itoa(e.Day()) + " " + monthNames[e.Month()] + " " + strconv.Itoa(e.Year())
	}
	return strconv.Itoa(s.Day()) + " " + monthNames[s.Month()] + " " + strconv.Itoa(s.Year())
}

// action is one row action as the page writes it: what it says, where it
// goes, whether it opens a drawer, its title, and for the reader's own open
// work whether Complete is offered with it.
type action struct {
	text, url, description string
	drawer, own, complete  bool
}

// nextAction is my_plan.services.compute_next_action.
func nextAction(a *activity, today time.Time, advances []advance) action {
	partner := a.delivery == "partner"
	id := a.id
	na := rules.NextAction
	if a.status == "awaiting_owner_approval" {
		return action{text: "Waiting for owner approval", url: "/planning/visit-requests",
			description: "The school's owner has been asked to approve this visit"}
	}
	if a.status == "returned" || a.status == "returned_by_pl" || a.status == "returned_by_ia" {
		if partner {
			return action{text: "Correct Returned Evidence", url: "/partner/activities/" + id + "/evidence", description: "Returned for correction"}
		}
		return action{text: "Fix and Resubmit", url: "/activities/" + id + "/complete", description: "Returned for correction"}
	}
	if partner && a.evidence == "uploaded" && !in([]string{"closed", "cancelled", "rejected", "ia_verified", "returned_by_ia", "awaiting_ia_verification"}, a.status) {
		return action{text: "Submit Evidence to IA", url: "/partner/activities/" + id + "/evidence",
			description: "Evidence uploaded — submit it to IA for verification"}
	}
	if (a.status == "scheduled" || a.status == "rescheduled" || a.status == "partner_scheduled") && a.planned != nil && a.planned.Equal(today) {
		u := "/activities/" + id + "/start"
		if partner {
			u = "/partner/activities/" + id + "/evidence"
		}
		return action{text: "Start", url: u, description: "Due today"}
	}
	if a.status == "partner_scheduled" && partner && a.planned != nil && a.planned.After(today) {
		return action{text: "Prepare", url: "/my-plan/" + id, description: "Booked — review the plan and prepare"}
	}
	if a.status == "in_progress" {
		return action{text: "Complete Activity", url: "/activities/" + id + "/complete", description: "In Progress"}
	}
	worked := in(na.WorkedStatuses, a.status)
	if partner && a.evidence == "none" && worked {
		return action{text: "Upload Evidence", url: "/activities/" + id + "/evidence", description: "Evidence missing"}
	}
	if !partner && a.evidence == "none" && worked && a.status != "completed" {
		return action{text: "Complete Activity", url: "/activities/" + id + "/complete", description: "Enter the Salesforce ID to complete"}
	}
	formMet := a.evidence == "uploaded" || (!partner && a.evidence == "none")
	if worked && formMet && !isSet(a.salesforce) {
		return action{text: "Enter Activity SF ID", url: "/activities/" + id + "/salesforce-id", description: "Salesforce ID missing"}
	}
	if worked && formMet && isSet(a.salesforce) {
		done := true
		if in(na.SubmitNeedsParticipantsTypes, a.activityType) {
			n := 0
			if a.teachersAttended != nil {
				n += *a.teachersAttended
			}
			if a.leadersAttended != nil {
				n += *a.leadersAttended
			}
			done = n > 0
		}
		if done {
			return action{text: "Submit", url: "/activities/" + id + "/submit", description: "Ready for PL/IA review"}
		}
	}
	if in([]string{"baseline_ssa_visit", "school_visit_ssa_collection", "partner_ssa_collection", "cluster_training_ssa_collection"}, a.activityType) &&
		isSet(a.schoolPK) && str(a.schoolSSA) != "done" {
		return action{text: "Upload SSA", url: "/activities/" + id + "/complete", description: "SSA expected but not uploaded"}
	}
	if a.status == "awaiting_ia_verification" && a.iaVerification == "pending" {
		return action{text: "View Status", url: "/my-plan/" + id, description: "Waiting for verification"}
	}
	if a.status == "ia_verified" && a.iaVerification == "confirmed" && in([]string{"none", "pending_ia", "ia_confirmed"}, a.payment) {
		return action{text: "View Accounts Status", url: "/my-plan/" + id, description: "Accounts clearance pending"}
	}
	for _, adv := range advances {
		if adv.status == "reimbursement_disbursed" && !adv.receiptConfirmed {
			return action{text: "Confirm Reimbursement Receipt", url: "/my-plan/" + id + "/confirm-reimbursement-receipt",
				description: "Reimbursement sent — confirm you received it"}
		}
	}
	for _, adv := range advances {
		if adv.status == "disbursed" && !isSet(adv.netsuite) {
			return action{text: "Submit Accountability", url: "/my-plan/" + id + "/accountability",
				description: "Disbursed — submit spend, receipts & NetSuite Code"}
		}
	}
	for _, adv := range advances {
		if adv.status == "accountability_pending" {
			return action{text: "Awaiting Finance Clearance", url: "/my-plan/" + id,
				description: "Accountability submitted — Accountant review pending"}
		}
	}
	for _, adv := range advances {
		switch adv.status {
		case "accountability_pl_pending":
			return action{text: "Awaiting PL Accountability Approval", url: "/my-plan/" + id,
				description: "Accountability submitted — Programme Lead approval pending"}
		case "reimbursement_pl_pending":
			return action{text: "Awaiting PL Claim Approval", url: "/my-plan/" + id,
				description: "Self-funded claim submitted — Programme Lead approval pending"}
		case "reimbursement_submitted":
			return action{text: "Awaiting Reimbursement", url: "/my-plan/" + id,
				description: "Claim approved — Accountant reimbursement pending"}
		}
	}
	return action{text: "View Details", url: "/my-plan/" + id, description: "Scheduled / Waiting"}
}

// tableAction is work_plan_tables.work_plan_action, nil where it offers
// nothing.
func tableAction(a *activity, owned, enabled bool, recipient, recipientName, recipientLabel string) *action {
	if in(rules.CompletedWorkStatuses, a.status) || a.status == "cancelled" || a.status == "rejected" || a.status == "deferred" {
		return &action{text: "View", url: "/my-plan/" + a.id, description: "View activity record"}
	}
	if owned && enabled && a.delivery != "partner" && in(rules.Table.OpenToItsOwner, a.status) {
		text := "Schedule"
		if dated(a) {
			text = "Reschedule"
		}
		return &action{text: text, url: "/my-plan/" + a.id + "/reschedule-drawer", drawer: true,
			description: "Schedule or change the date of this existing activity", own: true,
			complete: dated(a) && (a.status == "scheduled" || a.status == "rescheduled")}
	}
	if !owned && enabled && recipient != "" {
		to := recipientLabel
		description := "Review an activity-linked message before sending"
		if recipientLabel == "" {
			to = recipientName
		} else {
			description = "Review an activity-linked message to " + recipientName + " before sending"
		}
		q := url.Values{"context_type": {"activity"}, "context_id": {a.id}, "to": {recipient}}
		return &action{text: "Send to " + to, url: "/messages/new?" + encodeOrdered(q, "context_type", "context_id", "to"), description: description}
	}
	return nil
}

func encodeOrdered(q url.Values, keys ...string) string {
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(q.Get(k)))
	}
	return strings.Join(parts, "&")
}

// opens is can_open_url for the links a row writes, by the role's exported
// answers.
func opens(door Door, link string) bool {
	path := link
	if i := strings.IndexByte(path, '?'); i >= 0 {
		path = path[:i]
	}
	parts := strings.Split(strings.Trim(path, "/"), "/")
	key := ""
	switch {
	case len(parts) == 2 && parts[0] == "my-plan":
		key = "record"
	case len(parts) == 3 && parts[0] == "my-plan":
		key = map[string]string{"reschedule-drawer": "reschedule", "confirm-reimbursement-receipt": "reimbursement_receipt",
			"accountability": "accountability"}[parts[2]]
	case len(parts) == 3 && parts[0] == "activities":
		key = map[string]string{"complete": "complete", "start": "start", "evidence": "evidence",
			"salesforce-id": "salesforce_id", "submit": "submit"}[parts[2]]
	case len(parts) == 4 && parts[0] == "partner" && parts[1] == "activities" && parts[3] == "evidence":
		key = "partner_evidence"
	case path == "/messages/new":
		key = "message"
	case path == "/planning/visit-requests":
		key = "visit_requests"
	}
	open, ok := door.Opens[key]
	if !ok {
		panic("workplan: no exported answer for the link " + link)
	}
	return open
}
