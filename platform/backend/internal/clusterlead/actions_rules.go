package clusterlead

import (
	"crypto/rand"
	"fmt"
	"slices"
	"time"
)

// The Cluster Action Register's rules that need no database: what an action
// may name, how each school's progress reads from its linked official
// activity, and how the action as a whole reads from its schools. An action
// is a coordination record; the activity's own state machine stays the
// authority on what was delivered (owner brief, 2026-11-11, part 7).

// supportKinds are what a leader may ask for. A training names one of the
// governed courses (activity_catalogue_item); the others are the existing
// kinds of school support, not a new taxonomy.
var supportKinds = []Choice{
	{"training", "Training"},
	{"school_visit", "School follow-up visit"},
	{"ssa_support", "SSA support"},
	{"classroom_coaching", "Classroom coaching"},
	{"leadership", "School leadership development"},
	{"teacher_development", "Teacher development"},
	{"participation", "Cluster attendance and participation"},
	{"operational", "School operational challenge"},
	{"partner_support", "Partner support request"},
	{"edtech", "Education technology support"},
	{"financial_literacy", "School financial literacy"},
	{"financing_referral", "School financing referral"},
	{"other", "Other school-development need"},
}

// actionSources says where a need was raised.
var actionSources = []Choice{
	{"meeting", "Cluster meeting"},
	{"school_follow_up", "School follow-up"},
	{"observation", "Cluster Leader observation"},
	{"other", "Other"},
}

// Choice is a value and its words.
type Choice struct{ Value, Label string }

func labelIn(choices []Choice, value string) string {
	for _, c := range choices {
		if c.Value == value {
			return c.Label
		}
	}
	return value
}

func validChoice(choices []Choice, value string) bool {
	return slices.ContainsFunc(choices, func(c Choice) bool { return c.Value == value })
}

// Why staff return or decline a request (brief 7.3); a note is always kept too.
var returnReasons = []Choice{
	{"already_scheduled", "School already scheduled for this support"},
	{"needs_clarification", "Request needs clarification"},
	{"not_eligible", "School not eligible for this activity"},
	{"unavailable", "Requested support unavailable"},
	{"wrong_staff", "Incorrect responsible staff"},
	{"duplicate", "Duplicate of an existing request"},
	{"other", "Other"},
}

// School coordination states, stored.
const (
	schoolDraft          = "draft"
	schoolAwaiting       = "awaiting_review"
	schoolUnderReview    = "under_review"
	schoolClarification  = "clarification_requested"
	schoolAccepted       = "accepted"
	schoolReturned       = "returned"
	schoolDeclined       = "declined"
	schoolCancelled      = "cancelled"
	progressPlanned      = "planned"
	progressInProgress   = "in_progress"
	progressImplemented  = "implementation_recorded"
	progressVerified     = "verified"
	progressReplanNeeded = "replan"
)

// Official activity statuses (apps/core/enums.py ActivityStatus) by the
// progress they show. Evidence uploaded is never verification: only an
// approved completion (completed and after) is.
var (
	activityPlanned     = []string{"planned", "scheduled", "rescheduled", "assigned_to_partner", "partner_scheduled", "awaiting_owner_approval"}
	activityStarted     = []string{"in_progress", "completion_started"}
	activityImplemented = []string{"evidence_uploaded", "evidence_accepted", "salesforce_id_required", "submitted_to_pl",
		"returned_by_pl", "awaiting_ia_verification", "returned_by_ia"}
	activityVerified = []string{"completed", "ia_verified", "accountant_confirmed", "closed"}
	activityEnded    = []string{"cancelled", "rejected", "deferred", "returned", "not_planned"}
)

// schoolProgress is how far a school's support has got: its coordination
// state until an activity is linked, then the linked activity's own state.
func schoolProgress(status, activityStatus string, hasActivity bool) string {
	if status != schoolAccepted || !hasActivity {
		return status
	}
	switch {
	case slices.Contains(activityVerified, activityStatus):
		return progressVerified
	case slices.Contains(activityImplemented, activityStatus):
		return progressImplemented
	case slices.Contains(activityStarted, activityStatus):
		return progressInProgress
	case slices.Contains(activityEnded, activityStatus):
		return progressReplanNeeded
	default:
		return progressPlanned
	}
}

// progressWords are each progress's label and tone (the tone is never the
// only signal: the label always says it).
var progressWords = map[string][2]string{
	schoolDraft:          {"Draft", "plain"},
	schoolAwaiting:       {"Awaiting CCEO review", "info"},
	schoolUnderReview:    {"Under review", "info"},
	schoolClarification:  {"Clarification requested", "caution"},
	schoolAccepted:       {"Accepted — to be planned", "info"},
	schoolReturned:       {"Returned", "alert"},
	schoolDeclined:       {"Declined", "alert"},
	schoolCancelled:      {"Cancelled", "plain"},
	progressPlanned:      {"Planned", "info"},
	progressInProgress:   {"In progress", "info"},
	progressImplemented:  {"Implementation recorded — awaiting verification", "caution"},
	progressVerified:     {"Verified", "good"},
	progressReplanNeeded: {"Planned activity cancelled — to be re-planned", "caution"},
}

func progressLabel(progress string) (string, string) {
	if words, ok := progressWords[progress]; ok {
		return words[0], words[1]
	}
	return progress, "plain"
}

// progressOrder ranks how far a school has got, least first, so an action
// reads as its least advanced live school: one school's verified support
// never shows the action done.
var progressOrder = []string{
	schoolDraft, schoolClarification, schoolAwaiting, schoolUnderReview, schoolAccepted,
	progressReplanNeeded, progressPlanned, progressInProgress, progressImplemented, progressVerified,
}

// finished: a school needing nothing more from anyone.
func finished(progress string) bool {
	return progress == progressVerified || progress == schoolReturned || progress == schoolDeclined || progress == schoolCancelled
}

// actionOverall reads an action from its own state and its schools'
// progress: (status key, label, tone, "2 of 5 schools verified").
func actionOverall(status string, progresses []string) (string, string, string, string) {
	switch status {
	case "draft":
		return "draft", "Draft", "plain", ""
	case "cancelled":
		return "cancelled", "Cancelled", "plain", ""
	case "closed":
		return "closed", "Closed", "good", summaryOf(progresses)
	}
	least, waitingOnLeader, allDone := "", false, len(progresses) > 0
	for _, p := range progresses {
		if p == schoolClarification || p == schoolReturned {
			waitingOnLeader = true
		}
		if !finished(p) {
			allDone = false
			if least == "" || slices.Index(progressOrder, p) < slices.Index(progressOrder, least) {
				least = p
			}
		}
	}
	switch {
	case allDone:
		return "review_due", "Support done — review and close", "good", summaryOf(progresses)
	case waitingOnLeader && least == schoolClarification:
		return "needs_reply", "Clarification requested", "caution", summaryOf(progresses)
	}
	label, tone := progressLabel(least)
	return least, label, tone, summaryOf(progresses)
}

func summaryOf(progresses []string) string {
	verified := 0
	for _, p := range progresses {
		if p == progressVerified {
			verified++
		}
	}
	if len(progresses) == 1 {
		label, _ := progressLabel(progresses[0])
		return label
	}
	return fmt.Sprintf("%d of %d schools verified", verified, len(progresses))
}

// actionTab is where an action sits in the leader's register: open (the
// leader's move), waiting (staff's move or support under way), completed.
func actionTab(status string, progresses []string) string {
	key, _, _, _ := actionOverall(status, progresses)
	switch key {
	case "closed", "cancelled":
		return "completed"
	case "draft", "needs_reply", "review_due":
		return "open"
	}
	for _, p := range progresses {
		if p == schoolReturned || p == schoolClarification {
			return "open"
		}
	}
	return "waiting"
}

// supportQueue is a school request's queue for staff (brief 5.3).
func supportQueue(progress string, overdue bool) string {
	switch {
	case overdue && !finished(progress):
		return "overdue"
	case progress == schoolAwaiting || progress == schoolUnderReview:
		return "new"
	case progress == schoolClarification:
		return "clarification"
	case progress == schoolAccepted || progress == progressReplanNeeded:
		return "accepted"
	case progress == progressPlanned:
		return "planned"
	case progress == progressInProgress || progress == progressImplemented:
		return "in_progress"
	case progress == progressVerified:
		return "completed"
	}
	return "closed"
}

// newRef is a short reference such as "CA-7K3P9Q": no 0/O or 1/I to misread.
func newRef() (string, error) {
	const alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
	raw := make([]byte, 6)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	out := []byte("CA-")
	for _, b := range raw {
		out = append(out, alphabet[int(b)%len(alphabet)])
	}
	return string(out), nil
}

// daysBetween counts whole calendar days from a to b.
func daysBetween(a, b time.Time) int {
	a = time.Date(a.Year(), a.Month(), a.Day(), 0, 0, 0, 0, time.UTC)
	b = time.Date(b.Year(), b.Month(), b.Day(), 0, 0, 0, 0, time.UTC)
	return int(b.Sub(a).Hours() / 24)
}
