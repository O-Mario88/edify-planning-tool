package clusterlead

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"time"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// actionViewer is who the caller is to an action: its cluster's leader, the
// cluster's staff, or a staff member a school's request is routed to.
type actionViewer struct {
	principal auth.Principal
	isLeader  bool
	// Staff-profile and user ids that count as the caller's own.
	own []string
	// The caller manages the cluster (Admin, Program Lead, its CCEO).
	managesCluster bool
}

// mayRespond: the school's request is routed to the caller, as its
// responsible CCEO or (for their team, or when nobody held the school) its
// supervising Program Lead.
func (v actionViewer) mayRespond(s ActionSchoolRecord) bool {
	if v.isLeader {
		return false
	}
	return (s.ResponsibleStaffID != "" && slices.Contains(v.own, s.ResponsibleStaffID)) ||
		(s.SupervisorStaffID != "" && slices.Contains(v.own, s.SupervisorStaffID))
}

// canSee: the caller may read the action at all.
func (v actionViewer) canSee(a ActionRecord) bool {
	if v.isLeader || v.managesCluster {
		return true
	}
	return slices.ContainsFunc(a.Schools, v.mayRespond)
}

func (s *ActionService) progressOf(r ActionSchoolRecord) string {
	return schoolProgress(r.Status, r.ActivityStatus, r.ActivityID != "")
}

func (s *ActionService) progresses(a ActionRecord) []string {
	if a.Status == "draft" {
		out := make([]string, len(a.SchoolIDs))
		for i := range out {
			out[i] = schoolDraft
		}
		return out
	}
	out := make([]string, len(a.Schools))
	for i, school := range a.Schools {
		out[i] = s.progressOf(school)
	}
	return out
}

func (s *ActionService) overdue(a ActionRecord, progresses []string) bool {
	if a.Status != "submitted" || !a.TargetOn.Before(s.ops.today()) {
		return false
	}
	return slices.ContainsFunc(progresses, func(p string) bool { return !finished(p) })
}

var eventLabels = map[string]string{
	"drafted": "Draft saved", "edited": "Draft edited", "submitted": "Sent for support", "routed": "Routed",
	"acknowledged": "Acknowledged", "accepted": "Accepted", "clarification_requested": "Clarification requested",
	"returned": "Returned", "declined": "Declined", "replied": "Leader replied", "linked": "Activity linked",
	"unlinked": "Activity unlinked", "reviewed": "Reviewed at a meeting", "escalated": "Escalated",
	"escalation_resolved": "Escalation resolved", "reminded": "Reminder sent", "closed": "Closed", "cancelled": "Cancelled",
	"overdue": "Past its target date",
}

func (s *ActionService) card(a ActionRecord, v actionViewer) *clustersv1.ActionCard {
	progresses := s.progresses(a)
	key, label, tone, summary := actionOverall(a.Status, progresses)
	card := &clustersv1.ActionCard{
		Id: a.ID, Ref: a.Ref, Title: a.Title, ClusterName: a.ClusterName, Status: key, StatusLabel: label,
		StatusTone: tone, ProgressSummary: summary, TargetOn: a.TargetOn.Format(isoDate),
		IsOverdue: s.overdue(a, progresses), Priority: a.Priority,
	}
	count := len(a.Schools)
	if a.Status == "draft" {
		count = len(a.SchoolIDs)
	}
	switch {
	case count == 1 && len(a.Schools) == 1:
		card.SchoolsLabel = a.Schools[0].Name
	default:
		card.SchoolsLabel = fmt.Sprintf("%d schools", count)
	}
	var responsible []string
	for _, school := range a.Schools {
		name := school.ResponsibleStaff
		if name == "" {
			name = map[string]string{"supervisor": "Program Lead (to assign)", "unassigned": "To be assigned"}[school.RoutedTo]
		}
		if name != "" && !slices.Contains(responsible, name) {
			responsible = append(responsible, name)
		}
	}
	switch len(responsible) {
	case 0:
	case 1:
		card.Responsible = responsible[0]
	default:
		card.Responsible = fmt.Sprintf("%s +%d", responsible[0], len(responsible)-1)
	}
	if a.LatestEvent != "" && a.LatestEventAt != nil {
		card.LatestUpdate = fmt.Sprintf("%s · %s", eventLabels[a.LatestEvent], a.LatestEventAt.In(s.ops.location).Format("2 Jan"))
	}
	switch {
	case v.isLeader && key == "draft":
		card.NextAction = "Send for support"
	case v.isLeader && (key == "needs_reply" || slices.Contains(progresses, schoolReturned) && a.Status == "submitted"):
		card.NextAction = "Reply"
	case v.isLeader && key == "review_due":
		card.NextAction = "Review and close"
	case !v.isLeader && slices.ContainsFunc(a.Schools, func(r ActionSchoolRecord) bool {
		p := s.progressOf(r)
		return v.mayRespond(r) && (p == schoolAwaiting || p == schoolUnderReview)
	}):
		card.NextAction = "Respond"
	case !v.isLeader && slices.ContainsFunc(a.Schools, func(r ActionSchoolRecord) bool {
		p := s.progressOf(r)
		return v.mayRespond(r) && (p == schoolAccepted || p == progressReplanNeeded)
	}):
		card.NextAction = "Plan and link"
	default:
		card.NextAction = "View progress"
	}
	return card
}

func (s *ActionService) linked(r ActionSchoolRecord) *clustersv1.LinkedActivity {
	if r.ActivityID == "" {
		return nil
	}
	out := &clustersv1.LinkedActivity{Id: r.ActivityID, Name: r.ActivityName, Status: r.ActivityStatus,
		StatusLabel: activityStatusLabel(r.ActivityStatus)}
	if r.ActivityDate != nil {
		out.Date = r.ActivityDate.Format(isoDate)
	}
	return out
}

// activityStatusLabel words an official activity's status
// (apps/core/enums.py ActivityStatus labels).
func activityStatusLabel(status string) string {
	labels := map[string]string{
		"not_planned": "Not Planned", "awaiting_owner_approval": "Awaiting Owner Approval", "planned": "Planned",
		"scheduled": "Scheduled", "assigned_to_partner": "Assigned to Partner", "partner_scheduled": "Partner Scheduled",
		"in_progress": "In Progress", "completion_started": "Completion Started", "evidence_uploaded": "Evidence Uploaded",
		"evidence_accepted": "Evidence Accepted", "salesforce_id_required": "Salesforce ID Required",
		"submitted_to_pl": "Submitted to PL", "returned_by_pl": "Returned by PL",
		"awaiting_ia_verification": "Awaiting IA Verification", "ia_verified": "IA Verified",
		"accountant_confirmed": "Accountant Confirmed", "completed": "Completed", "returned": "Returned",
		"returned_by_ia": "Returned by IA", "closed": "Closed", "rejected": "Rejected", "rescheduled": "Rescheduled",
		"cancelled": "Cancelled", "deferred": "Deferred",
	}
	if label, ok := labels[status]; ok {
		return label
	}
	return status
}

// view is the full action for the caller.
func (s *ActionService) view(ctx context.Context, a ActionRecord, v actionViewer) (*clustersv1.ClusterActionView, error) {
	events, reviews, escalations, err := s.store.ActionHistory(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	progresses := s.progresses(a)
	key, _, _, _ := actionOverall(a.Status, progresses)
	out := &clustersv1.ClusterActionView{
		Card: s.card(a, v), ClusterId: a.ClusterID, Source: a.Source, SourceLabel: labelIn(actionSources, a.Source),
		SourceMeeting: a.SourceMeeting, SupportKind: a.SupportKind, SupportKindLabel: labelIn(supportKinds, a.SupportKind),
		TrainingCourse: a.TrainingCourse, Description: a.Description, ExpectedOutcome: a.ExpectedOutcome,
		CreatedBy: a.CreatedByName, CreatedAt: a.CreatedAt.In(s.ops.location).Format(isoDate), FiscalYear: a.FiscalYear,
		CloseSummary: a.CloseSummary, Version: a.Version, SchoolIds: a.SchoolIDs, TrainingCourseId: a.TrainingCourseID,
		SourceActivityId: a.SourceActivityID, SourcePlanId: a.SourcePlanID, Priority: a.Priority,
		TargetOn: a.TargetOn.Format(isoDate), Title: a.Title,
	}
	var lastVerified time.Time
	allVerified := len(a.Schools) > 0
	for _, r := range a.Schools {
		p := s.progressOf(r)
		label, tone := progressLabel(p)
		row := &clustersv1.ActionSchool{
			SchoolId: r.SchoolID, EdifySchoolId: r.EdifySchoolID, Name: r.Name, ResponsibleStaff: r.ResponsibleStaff,
			RoutedTo: r.RoutedTo, Progress: p, ProgressLabel: label, ProgressTone: tone, Note: r.Note,
			Activity: s.linked(r),
			CanRespond: v.mayRespond(r) && a.Status == "submitted" &&
				slices.Contains([]string{schoolAwaiting, schoolUnderReview}, r.Status),
			CanLink: v.mayRespond(r) && a.Status == "submitted" && r.Status == schoolAccepted,
		}
		out.Schools = append(out.Schools, row)
		if p != progressVerified {
			allVerified = false
		} else if r.UpdatedAt.After(lastVerified) {
			lastVerified = r.UpdatedAt
		}
	}
	if allVerified && a.SubmittedAt != nil {
		out.ResolutionDays = int32(max(daysBetween(*a.SubmittedAt, lastVerified), 0)) // #nosec G115 -- days
	}
	for _, e := range events {
		out.History = append(out.History, &clustersv1.ActionEvent{Event: e.Event, Label: eventLabels[e.Event],
			Actor: e.Actor, ActorRole: e.ActorRole, School: e.School, Note: e.Note, At: e.At.In(s.ops.location).Format("2006-01-02 15:04")})
	}
	for _, r := range reviews {
		out.Reviews = append(out.Reviews, &clustersv1.ActionReview{Id: r.ID, Meeting: r.Meeting, Progress: r.Progress,
			Challenges: r.Challenges, NextStep: r.NextStep, Outcome: r.Outcome, By: r.By, At: r.At.In(s.ops.location).Format(isoDate)})
	}
	for _, x := range escalations {
		out.Escalations = append(out.Escalations, &clustersv1.ActionEscalation{Id: x.ID, Reason: x.Reason, RaisedBy: x.RaisedBy,
			ToStaff: x.ToStaff, Status: x.Status, Resolution: x.Resolution, At: x.At.In(s.ops.location).Format(isoDate),
			CanResolve: x.Status == "open" && slices.Contains(v.own, x.ToStaffID)})
	}
	isLive := a.Status == "submitted"
	out.CanEdit = v.isLeader && a.Status == "draft"
	out.CanSubmit = out.CanEdit
	out.CanCancel = v.isLeader && (a.Status == "draft" || isLive)
	out.CanClose = v.isLeader && key == "review_due"
	out.CanReview = v.isLeader && isLive
	out.CanEscalate = v.isLeader && isLive && key != "review_due"
	out.CanReply = v.isLeader && isLive && slices.ContainsFunc(a.Schools, func(r ActionSchoolRecord) bool {
		return r.Status == schoolClarification || r.Status == schoolReturned
	})
	return out, nil
}

// sortCards puts the leader's most pressing first: overdue, then by target.
func sortCards(cards []*clustersv1.ActionCard) {
	sort.SliceStable(cards, func(i, j int) bool {
		if cards[i].GetIsOverdue() != cards[j].GetIsOverdue() {
			return cards[i].GetIsOverdue()
		}
		return cards[i].GetTargetOn() < cards[j].GetTargetOn()
	})
}
