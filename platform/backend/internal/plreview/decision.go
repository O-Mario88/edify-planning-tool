package plreview

import (
	"context"
	"slices"
	"strings"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"
)

const (
	maxReturnNote      = 512 // apps.activities.return_notes.NOTE_MAX
	statusVerified     = "ia_verified"
	statusReturnedByPL = "returned_by_pl"

	eventVerifiedByPL = "activity_verified_by_pl"
	eventReturnedByPL = "activity_returned_by_pl"
	eventAwaitingLead = "activity_submitted_for_review"
	eventAwaitingIA   = "activity_submitted_for_verification"

	notificationCategory = "activity"
	isoSeconds           = "2006-01-02T15:04:05"
	isoMicroseconds      = "2006-01-02T15:04:05.000000"
	isoUTCOffset         = "+00:00"
)

// ReturnReasonValue is a reason as a checklist sends it. A checklist's value
// is its ticks joined by commas, so a reason's own commas are left out.
func ReturnReasonValue(reason string) string { return strings.ReplaceAll(reason, ",", "") }

// TickedReasons reads a checklist's value back into the reasons as written.
// A value that is not one of them is kept, as the existing view keeps it.
func TickedReasons(value string) []string {
	written := make(map[string]string, len(rules.ReturnReasons))
	for _, reason := range rules.ReturnReasons {
		written[ReturnReasonValue(reason)] = reason
	}
	ticked := []string{}
	for _, part := range strings.Split(value, ",") {
		if part == "" {
			continue
		}
		if reason, ok := written[part]; ok {
			part = reason
		}
		ticked = append(ticked, part)
	}
	return ticked
}

// composeReturnNote is return_notes.compose: the ticked reasons and the
// written explanation, as one sentence for the officer.
func composeReturnNote(reasons []string, written string) string {
	picked := make([]string, 0, len(reasons))
	for _, reason := range reasons {
		if reason = strings.TrimSpace(reason); reason != "" {
			picked = append(picked, reason)
		}
	}
	head := strings.Join(picked, "; ")
	written = strings.TrimSpace(written)
	switch {
	case head != "" && written != "":
		return fitNote(head + " — " + written)
	case head != "":
		return fitNote(head)
	}
	return fitNote(written)
}

// fitNote is return_notes.fit: cut to the column with a visible marker.
func fitNote(note string) string {
	note = strings.TrimSpace(note)
	characters := []rune(note)
	if len(characters) <= maxReturnNote {
		return note
	}
	return strings.TrimRightFunc(string(characters[:maxReturnNote-1]), unicode.IsSpace) + "…"
}

// returnAuditReason is the reason pl_return_action writes on its audit row.
func returnAuditReason(reasons []string, written string) string {
	if written == "" {
		return strings.Join(reasons, "; ")
	}
	return strings.Join(append(append([]string{}, reasons...), written), "; ")
}

// pythonISO is datetime.isoformat() of an aware time, in UTC.
func pythonISO(at time.Time) string {
	at = at.UTC()
	if at.Nanosecond()/int(time.Microsecond) == 0 {
		return at.Format(isoSeconds) + isoUTCOffset
	}
	return at.Format(isoMicroseconds) + isoUTCOffset
}

// activityBridgeStates are the states the Activity save bridge
// (business_transformation.signals._activity_state_bridge) raises
// bt.activity.state_changed for.
var activityBridgeStates = []string{"ia_verified", "accountant_confirmed", "closed", "returned", "returned_by_ia", "returned_by_pl"}

// RaiseActivitySaved is that bridge for an activity another save wrote in
// tx: its state change event, keyed by the IA confirmation's time or, with
// none, the save's own.
func RaiseActivitySaved(ctx context.Context, tx pgx.Tx, activityID, status string, iaConfirmedAt *time.Time, savedAt time.Time) error {
	if !slices.Contains(activityBridgeStates, status) {
		return nil
	}
	version := savedAt
	if iaConfirmedAt != nil {
		version = *iaConfirmedAt
	}
	return raiseEvents(ctx, tx, []outboxEvent{{Type: "bt.activity.state_changed",
		Key: "bt.activity.state:" + activityID + ":" + status + ":" + pythonISO(version), Payload: map[string]string{"activityId": activityID}}},
		savedAt)
}

// outboxEvent is one durable event a decision raises.
type outboxEvent struct {
	Type, Key string
	Payload   map[string]string
}

// reviewEvents is what saving the activity raises: the Business
// Transformation bridge always, the project's impact refresh for verified
// project work at a school, and the Salesforce sync when it is switched on.
// The version is the confirmation's time when the work holds one.
func reviewEvents(review Review, status string, at time.Time, salesforceSync bool) []outboxEvent {
	versionAt := at
	if review.IAConfirmedAt != nil && status != statusVerified {
		versionAt = *review.IAConfirmedAt
	}
	version := pythonISO(versionAt)
	events := []outboxEvent{{
		Type:    "bt.activity.state_changed",
		Key:     "bt.activity.state:" + review.ID + ":" + status + ":" + version,
		Payload: map[string]string{"activityId": review.ID},
	}}
	if status != statusVerified {
		return events
	}
	if review.ProjectID != "" && review.SchoolID != "" {
		events = append(events, outboxEvent{
			Type:    "projects.impact.refresh",
			Key:     "projects.impact:" + review.SchoolID + ":activity:" + review.ID + ":" + version,
			Payload: map[string]string{"schoolId": review.SchoolID},
		})
	}
	if salesforceSync {
		events = append(events, outboxEvent{
			Type:    "integrations.salesforce.activity",
			Key:     "sf:activity:" + review.ID,
			Payload: map[string]string{"activityId": review.ID},
		})
	}
	return events
}

// mayDecide is apps.pl_review.services.may_review, the view's door: whose
// completions this reviewer may decide, whatever state they are in.
func mayDecide(work reviewCase, by reviewerReach) bool {
	if by.admin {
		return true
	}
	if work.owner == "" {
		return false
	}
	for _, id := range by.own {
		if id == work.owner {
			return by.clearsOwn && work.deliveryType != partnerDelivery
		}
	}
	for _, id := range by.supervised {
		if id == work.owner {
			return true
		}
	}
	return false
}
