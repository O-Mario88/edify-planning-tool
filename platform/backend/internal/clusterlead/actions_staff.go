package clusterlead

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// The staff side of the register: the requests routed to a CCEO (and a
// Program Lead's team), their responses, and the link to the official
// activity that delivers each school's support. Staff never create or edit
// an activity here; they plan it in Edify's own planning and link it.

// staffQueue is the filter for the caller's own requests, or their team's.
func (s *ActionService) staffQueue(ctx context.Context, scope string) (QueueFilter, bool, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return QueueFilter{}, false, err
	}
	if principal.ActiveRole == RoleClusterLeader || principal.StaffProfileID == "" {
		return QueueFilter{}, false, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Cluster support requests are for Edify staff.")
	}
	supervisees, err := s.store.SuperviseesOf(ctx, principal.StaffProfileID)
	if err != nil {
		return QueueFilter{}, false, s.ops.internal(ctx, err)
	}
	hasTeam := len(supervisees) > 0 || anyClusterAdministrators[principal.ActiveRole]
	own := []string{principal.StaffProfileID}
	switch scope {
	case "", "mine":
		// A Program Lead's own schools, and requests routed to them to assign.
		return QueueFilter{Responsible: own, Supervisor: own}, hasTeam, nil
	case "team":
		if !hasTeam {
			return QueueFilter{}, false, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
				"You have no team.")
		}
		filter := QueueFilter{Responsible: supervisees, Supervisor: own, Unassigned: anyClusterAdministrators[principal.ActiveRole]}
		if filter.Unassigned {
			filter.UnassignedCountries = countryBound(principal)
		}
		return filter, true, nil
	}
	return QueueFilter{}, false, invalid(ctx, "The scope is mine or team.")
}

var supportQueues = []string{"new", "clarification", "accepted", "planned", "in_progress", "completed", "overdue"}

// ListSupportRequests is the caller's queue of cluster support requests.
func (s *ActionService) ListSupportRequests(
	ctx context.Context, request *connect.Request[clustersv1.ListSupportRequestsRequest],
) (*connect.Response[clustersv1.ListSupportRequestsResponse], error) {
	msg := request.Msg
	if err := s.ops.checkReady(ctx); err != nil {
		return nil, err
	}
	filter, hasTeam, err := s.staffQueue(ctx, msg.GetScope())
	if err != nil {
		return nil, err
	}
	if q := msg.GetQueue(); q != "" && !slices.Contains(supportQueues, q) {
		return nil, invalid(ctx, "Unknown queue.")
	}
	principal, _ := principalOf(ctx)
	v := actionViewer{principal: principal, own: ownIDs(principal)}
	actions, err := s.store.SupportQueue(ctx, filter, maxActionsListed)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	out := &clustersv1.ListSupportRequestsResponse{Counts: map[string]int32{}, HasTeam: hasTeam}
	var rows []*clustersv1.SupportRequestRow
	for _, a := range actions {
		for _, r := range a.Schools {
			p := s.progressOf(r)
			overdue := a.Status == "submitted" && a.TargetOn.Before(s.ops.today()) && !finished(p)
			queue := supportQueue(p, overdue)
			if a.Status == "closed" && queue != "completed" {
				continue
			}
			out.Counts[queue]++
			if want := msg.GetQueue(); (want == "" && queue == "completed") || (want != "" && want != queue) {
				continue
			}
			label, tone := progressLabel(p)
			row := &clustersv1.SupportRequestRow{
				ActionId: a.ID, Ref: a.Ref, ClusterId: a.ClusterID, ClusterName: a.ClusterName, Leader: a.CreatedByName,
				SchoolId: r.SchoolID, EdifySchoolId: r.EdifySchoolID, SchoolName: r.Name,
				Support: supportWords(a), Description: a.Description, ResponsibleStaff: r.ResponsibleStaff,
				RoutedTo: r.RoutedTo, Progress: p, ProgressLabel: label, ProgressTone: tone,
				TargetOn: a.TargetOn.Format(isoDate), IsOverdue: overdue, Priority: a.Priority,
				CanRespond: v.mayRespond(r) && a.Status == "submitted" && (r.Status == schoolAwaiting || r.Status == schoolUnderReview),
				CanLink:    v.mayRespond(r) && a.Status == "submitted" && r.Status == schoolAccepted,
			}
			if a.SubmittedAt != nil {
				row.SubmittedOn = a.SubmittedAt.In(s.ops.location).Format(isoDate)
				if !finished(p) {
					row.DaysWaiting = int32(max(daysBetween(*a.SubmittedAt, s.ops.now()), 0)) // #nosec G115 -- days
				}
			}
			rows = append(rows, row)
		}
	}
	sort.SliceStable(rows, func(i, j int) bool {
		if rows[i].GetIsOverdue() != rows[j].GetIsOverdue() {
			return rows[i].GetIsOverdue()
		}
		return rows[i].GetTargetOn() < rows[j].GetTargetOn()
	})
	page, size, err := pageOf(ctx, msg.GetPage())
	if err != nil {
		return nil, err
	}
	start := min(int((page-1)*size), len(rows))
	end := min(start+int(size), len(rows))
	out.Rows = rows[start:end]
	out.Page = pageInfo(page, size, int64(len(rows)))
	return connect.NewResponse(out), nil
}

func supportWords(a ActionRecord) string {
	if a.TrainingCourse != "" {
		return "Training: " + a.TrainingCourse
	}
	return labelIn(supportKinds, a.SupportKind)
}

// responses are what staff may do with a request, from which states, to which.
var responses = map[string]struct {
	from     []string
	to       string
	event    string
	needNote bool
	needCode bool
	title    string
}{
	"acknowledge": {[]string{schoolAwaiting}, schoolUnderReview, "acknowledged", false, false, "Request acknowledged"},
	"accept":      {[]string{schoolAwaiting, schoolUnderReview}, schoolAccepted, "accepted", false, false, "Request accepted"},
	"clarify":     {[]string{schoolAwaiting, schoolUnderReview}, schoolClarification, "clarification_requested", true, false, "Clarification requested"},
	"return":      {[]string{schoolAwaiting, schoolUnderReview}, schoolReturned, "returned", true, true, "Request returned"},
	"decline":     {[]string{schoolAwaiting, schoolUnderReview}, schoolDeclined, "declined", true, true, "Request declined"},
}

// RespondToRequest is the staff member's answer to one school's request.
// Nothing is rejected silently: returning or declining needs a reason.
func (s *ActionService) RespondToRequest(
	ctx context.Context, request *connect.Request[clustersv1.RespondToRequestRequest],
) (*connect.Response[clustersv1.RespondToRequestResponse], error) {
	msg := request.Msg
	a, v, err := s.load(ctx, msg.GetActionId())
	if err != nil {
		return nil, err
	}
	r, err := s.routedSchool(ctx, a, v, msg.GetSchoolId())
	if err != nil {
		return nil, err
	}
	rule, ok := responses[msg.GetResponse()]
	if !ok {
		return nil, invalid(ctx, "Choose acknowledge, accept, ask for clarification, return or decline.")
	}
	note, err := textOf(ctx, "A note", msg.GetNote(), maxTextLength, rule.needNote)
	if err != nil {
		return nil, err
	}
	if rule.needCode {
		if !validChoice(returnReasons, msg.GetReasonCode()) {
			return nil, invalid(ctx, "Choose the reason.")
		}
		note = labelIn(returnReasons, msg.GetReasonCode()) + ": " + note
	}
	if !slices.Contains(rule.from, r.Status) {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"This request has moved on since you opened it.")
	}
	write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: rule.event, School: r.SchoolID, FromStatus: r.Status, ToStatus: rule.to, Note: note}}}
	if msg.GetResponse() != "acknowledge" {
		body := fmt.Sprintf("%s for %s (%s), by %s.", rule.title, r.Name, a.Ref, v.principal.Name)
		if note != "" {
			body += " " + note
		}
		notices, err := s.leaderNotices(ctx, a, "cluster_action_"+rule.event, rule.title, body,
			fmt.Sprintf("%s:%s:%s:%d", rule.event, a.ID, r.SchoolID, time.Now().UnixNano()), v.principal.UserID)
		if err != nil {
			return nil, s.ops.internal(ctx, err)
		}
		write.Notices = notices
	}
	if err := s.store.MoveSchool(ctx, a.ID, r.SchoolID, rule.from, rule.to, note, write); err != nil {
		return nil, s.writeErr(ctx, err)
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.RespondToRequestResponse{Action: view}), nil
}

// routedSchool is the school's request when it is routed to the caller.
func (s *ActionService) routedSchool(ctx context.Context, a ActionRecord, v actionViewer, schoolID string) (ActionSchoolRecord, error) {
	if a.Status != "submitted" {
		return ActionSchoolRecord{}, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"This action is no longer open.")
	}
	for _, r := range a.Schools {
		if r.SchoolID != schoolID {
			continue
		}
		if !v.mayRespond(r) {
			return ActionSchoolRecord{}, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
				"This school's request is routed to another member of staff.")
		}
		return r, nil
	}
	return ActionSchoolRecord{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "That school is not part of this action.")
}

// ListLinkableActivities is the school's official activities (and its
// cluster's) that may deliver the accepted support.
func (s *ActionService) ListLinkableActivities(
	ctx context.Context, request *connect.Request[clustersv1.ListLinkableActivitiesRequest],
) (*connect.Response[clustersv1.ListLinkableActivitiesResponse], error) {
	a, v, err := s.load(ctx, request.Msg.GetActionId())
	if err != nil {
		return nil, err
	}
	r, err := s.routedSchool(ctx, a, v, request.Msg.GetSchoolId())
	if err != nil {
		return nil, err
	}
	since := a.CreatedAt.AddDate(0, 0, -30)
	activities, err := s.store.LinkableActivities(ctx, r.SchoolID, a.ClusterID, since)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	out := &clustersv1.ListLinkableActivitiesResponse{}
	for _, act := range activities {
		item := &clustersv1.LinkedActivity{Id: act.ID, Name: act.Name, Status: act.Status, StatusLabel: activityStatusLabel(act.Status)}
		if act.Date != nil {
			item.Date = act.Date.Format(isoDate)
		}
		out.Activities = append(out.Activities, item)
	}
	return connect.NewResponse(out), nil
}

// LinkActivity links the official activity that delivers a school's accepted
// support; its id is the activity's own, never derived from the action.
func (s *ActionService) LinkActivity(
	ctx context.Context, request *connect.Request[clustersv1.LinkActivityRequest],
) (*connect.Response[clustersv1.LinkActivityResponse], error) {
	msg := request.Msg
	a, v, err := s.load(ctx, msg.GetActionId())
	if err != nil {
		return nil, err
	}
	r, err := s.routedSchool(ctx, a, v, msg.GetSchoolId())
	if err != nil {
		return nil, err
	}
	if r.Status != schoolAccepted {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"Accept the request before linking the activity that delivers it.")
	}
	if err := validID(ctx, "activity", msg.GetActivityId()); err != nil {
		return nil, err
	}
	school, cluster, status, err := s.store.ActivityReach(ctx, msg.GetActivityId())
	if errors.Is(err, ErrNotFound) || (err == nil && school != r.SchoolID && cluster != a.ClusterID) {
		return nil, invalid(ctx, "Choose one of this school's activities, or one of its cluster's.")
	}
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	if slices.Contains(activityEnded, status) {
		return nil, invalid(ctx, "That activity was cancelled or ended. Choose one that is planned or delivered.")
	}
	write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: "linked", School: r.SchoolID, Note: msg.GetActivityId()}}}
	notices, err := s.leaderNotices(ctx, a, "cluster_action_planned", "Support planned",
		fmt.Sprintf("Support for %s (%s) is planned in Edify: %s.", r.Name, a.Ref, activityStatusLabel(status)),
		fmt.Sprintf("planned:%s:%s:%s", a.ID, r.SchoolID, msg.GetActivityId()), v.principal.UserID)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	write.Notices = notices
	if err := s.store.LinkSchoolActivity(ctx, a.ID, r.SchoolID, msg.GetActivityId(), write); err != nil {
		return nil, s.writeErr(ctx, err)
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.LinkActivityResponse{Action: view}), nil
}

// UnlinkActivity removes a wrong link, with a reason; the history keeps it.
func (s *ActionService) UnlinkActivity(
	ctx context.Context, request *connect.Request[clustersv1.UnlinkActivityRequest],
) (*connect.Response[clustersv1.UnlinkActivityResponse], error) {
	msg := request.Msg
	a, v, err := s.load(ctx, msg.GetActionId())
	if err != nil {
		return nil, err
	}
	r, err := s.routedSchool(ctx, a, v, msg.GetSchoolId())
	if err != nil {
		return nil, err
	}
	if r.ActivityID == "" {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "No activity is linked.")
	}
	reason, err := textOf(ctx, "The reason", msg.GetReason(), maxReasonLength, true)
	if err != nil {
		return nil, err
	}
	write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: "unlinked", School: r.SchoolID, Note: r.ActivityID + ": " + reason}}}
	if err := s.store.LinkSchoolActivity(ctx, a.ID, r.SchoolID, "", write); err != nil {
		return nil, s.writeErr(ctx, err)
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.UnlinkActivityResponse{Action: view}), nil
}

// ResolveEscalation is the supervisor resolving an escalation routed to them.
func (s *ActionService) ResolveEscalation(
	ctx context.Context, request *connect.Request[clustersv1.ResolveEscalationRequest],
) (*connect.Response[clustersv1.ResolveEscalationResponse], error) {
	msg := request.Msg
	if err := validID(ctx, "escalation", msg.GetEscalationId()); err != nil {
		return nil, err
	}
	actionID, to, status, err := s.store.EscalationByID(ctx, msg.GetEscalationId())
	if errors.Is(err, ErrNotFound) {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such escalation.")
	}
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	a, v, err := s.load(ctx, actionID)
	if err != nil {
		return nil, err
	}
	if !slices.Contains(v.own, to) || status != "open" {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Only the person it was escalated to resolves an open escalation.")
	}
	resolution, err := textOf(ctx, "The resolution", msg.GetResolution(), maxTextLength, true)
	if err != nil {
		return nil, err
	}
	write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: "escalation_resolved", Note: resolution}}}
	notices, err := s.leaderNotices(ctx, a, "cluster_action_escalation_resolved", "Escalation resolved",
		fmt.Sprintf("%s (%s): %s", a.Title, a.Ref, resolution), "resolved:"+msg.GetEscalationId(), v.principal.UserID)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	write.Notices = notices
	if err := s.store.ResolveEscalation(ctx, msg.GetEscalationId(), a.ID, resolution, write); err != nil {
		return nil, s.writeErr(ctx, err)
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.ResolveEscalationResponse{Action: view}), nil
}

// GetClusterActionSummary is the cluster's action figures for the financial
// year, with School Support Resolution Time: days from a need being sent to
// support being verified (owner, 2026-11-11).
func (s *ActionService) GetClusterActionSummary(
	ctx context.Context, request *connect.Request[clustersv1.GetClusterActionSummaryRequest],
) (*connect.Response[clustersv1.GetClusterActionSummaryResponse], error) {
	if _, err := s.ops.access(ctx, request.Msg.GetClusterId()); err != nil {
		return nil, err
	}
	actions, err := s.store.ClusterActions(ctx, request.Msg.GetClusterId(), maxActionsListed)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	_, _, year := fiscalYear(s.ops.today())
	counts := map[string]int32{}
	needs := map[string]int32{}
	schools := map[string]int32{}
	names := map[string]string{}
	var resolution []int
	for _, a := range actions {
		if a.Status == "draft" || int(a.FiscalYear) != year {
			continue
		}
		counts["total"]++
		needs[labelIn(supportKinds, a.SupportKind)]++
		progresses := s.progresses(a)
		key, _, _, _ := actionOverall(a.Status, progresses)
		switch {
		case a.Status == "closed":
			counts["closed"]++
		case a.Status == "cancelled":
			counts["cancelled"]++
		case key == "review_due":
			counts["review_due"]++
		default:
			counts["open"]++
			if s.overdue(a, progresses) {
				counts["overdue"]++
			}
			if slices.ContainsFunc(progresses, func(p string) bool { return p == schoolAwaiting || p == schoolUnderReview }) {
				counts["waiting_on_staff"]++
			}
		}
		for _, r := range a.Schools {
			schools[r.SchoolID]++
			names[r.SchoolID] = r.Name
			if s.progressOf(r) == progressVerified && a.SubmittedAt != nil {
				counts["schools_verified"]++
				resolution = append(resolution, max(daysBetween(*a.SubmittedAt, r.UpdatedAt), 0))
			}
		}
	}
	out := &clustersv1.GetClusterActionSummaryResponse{ResolvedSchools: int32(len(resolution))} // #nosec G115 -- bounded
	for _, f := range []struct{ key, label string }{
		{"total", "Total actions"}, {"open", "Open"}, {"waiting_on_staff", "Waiting on staff"},
		{"overdue", "Overdue"}, {"review_due", "Done — to review"}, {"closed", "Closed"},
		{"schools_verified", "Schools with verified support"},
	} {
		out.Figures = append(out.Figures, &clustersv1.SummaryFigure{Key: f.key, Label: f.label, Value: counts[f.key]})
	}
	if len(resolution) > 0 {
		sort.Ints(resolution)
		out.MedianResolutionDays = int32(resolution[len(resolution)/2]) // #nosec G115 -- days
	}
	for label, n := range needs {
		out.Needs = append(out.Needs, &clustersv1.SummaryFigure{Key: label, Label: label, Value: n})
	}
	sort.Slice(out.Needs, func(i, j int) bool { return out.Needs[i].GetValue() > out.Needs[j].GetValue() })
	for id, n := range schools {
		if n >= 2 {
			out.RepeatSchools = append(out.RepeatSchools, &clustersv1.SummaryFigure{Key: id, Label: names[id], Value: n})
		}
	}
	sort.Slice(out.RepeatSchools, func(i, j int) bool { return out.RepeatSchools[i].GetValue() > out.RepeatSchools[j].GetValue() })
	return connect.NewResponse(out), nil
}

// GetSchoolSupportHistory is a school's cluster support, for staff who may
// see the school's cluster or its requests, or its cluster's leader.
func (s *ActionService) GetSchoolSupportHistory(
	ctx context.Context, request *connect.Request[clustersv1.GetSchoolSupportHistoryRequest],
) (*connect.Response[clustersv1.GetSchoolSupportHistoryResponse], error) {
	schoolID := request.Msg.GetSchoolId()
	if err := validID(ctx, "school", schoolID); err != nil {
		return nil, err
	}
	if err := s.ops.checkReady(ctx); err != nil {
		return nil, err
	}
	actions, err := s.store.SchoolActions(ctx, schoolID, maxActionsListed)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	out := &clustersv1.GetSchoolSupportHistoryResponse{}
	for _, a := range actions {
		if _, err := s.viewerOf(ctx, a); err != nil {
			continue // only what the caller may see; history is never widened
		}
		reviewNext := ""
		if _, reviews, _, err := s.store.ActionHistory(ctx, a.ID); err == nil && len(reviews) > 0 {
			reviewNext = reviews[len(reviews)-1].NextStep
		}
		for _, r := range a.Schools {
			if r.SchoolID != schoolID {
				continue
			}
			p := s.progressOf(r)
			label, tone := progressLabel(p)
			entry := &clustersv1.SchoolSupportEntry{ActionId: a.ID, Ref: a.Ref, ClusterName: a.ClusterName,
				Support: supportWords(a), Source: firstNonEmpty(a.SourceMeeting, labelIn(actionSources, a.Source)),
				ResponsibleStaff: r.ResponsibleStaff, Progress: p, ProgressLabel: label, ProgressTone: tone,
				Activity: s.linked(r), TargetOn: a.TargetOn.Format(isoDate), NextStep: reviewNext}
			if a.SubmittedAt != nil {
				entry.SubmittedOn = a.SubmittedAt.In(s.ops.location).Format(isoDate)
			}
			out.Entries = append(out.Entries, entry)
		}
	}
	return connect.NewResponse(out), nil
}
