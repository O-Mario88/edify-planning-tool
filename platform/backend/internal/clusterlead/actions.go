package clusterlead

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// ActionService implements ClusterActionService (owner brief, 2026-11-11,
// "Cluster Action & Follow-up Management System"). The leader raises a need;
// each school's request goes to the CCEO holding it; staff accept and plan
// the official activity in Edify and link it here; the activity's own state
// shows progress; the leader reviews it at the next meeting and closes it.
type ActionService struct {
	ops    *OperationsService
	store  *Store
	config ActionConfig
}

// ActionConfig is the follow-up policy; zero values take the defaults.
type ActionConfig struct {
	// Remind the responsible staff member after this many days unanswered.
	RemindAfterDays int
	// Escalate to the supervising Program Lead this many days past the target
	// date; 0 never escalates automatically.
	EscalateAfterDays int
}

const (
	defaultRemindDays    = 3
	maxActionsListed     = 500
	maxSchoolsPerAction  = 100
	maxIdempotencyLength = 100
)

// NewActions wires the action register onto the operations service.
func NewActions(ops *OperationsService, store *Store, config ActionConfig) *ActionService {
	if config.RemindAfterDays <= 0 {
		config.RemindAfterDays = defaultRemindDays
	}
	return &ActionService{ops: ops, store: store, config: config}
}

// viewerOf is the caller's side of an existing action, refused when they
// may not see it.
func (s *ActionService) viewerOf(ctx context.Context, a ActionRecord) (actionViewer, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return actionViewer{}, err
	}
	v := actionViewer{principal: principal, own: ownIDs(principal)}
	if principal.ActiveRole == RoleClusterLeader {
		if _, err := s.ops.liveFor(ctx, principal.UserID, a.ClusterID); err != nil {
			return actionViewer{}, err
		}
		v.isLeader = true
		return v, nil
	}
	if cluster, err := s.ops.data.Cluster(ctx, a.ClusterID); err == nil {
		v.managesCluster = mayAdminister(principal, cluster)
	}
	if !v.canSee(a) {
		return actionViewer{}, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"This action is not yours to see.")
	}
	return v, nil
}

func (s *ActionService) load(ctx context.Context, id string) (ActionRecord, actionViewer, error) {
	if err := validID(ctx, "action", id); err != nil {
		return ActionRecord{}, actionViewer{}, err
	}
	if err := s.ops.checkReady(ctx); err != nil {
		return ActionRecord{}, actionViewer{}, err
	}
	a, err := s.store.Action(ctx, id)
	if errors.Is(err, ErrNotFound) {
		return ActionRecord{}, actionViewer{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such action.")
	}
	if err != nil {
		return ActionRecord{}, actionViewer{}, s.ops.internal(ctx, err)
	}
	v, err := s.viewerOf(ctx, a)
	return a, v, err
}

// reply is the action as the caller now sees it.
func (s *ActionService) reload(ctx context.Context, id string) (*clustersv1.ClusterActionView, error) {
	a, v, err := s.load(ctx, id)
	if err != nil {
		return nil, err
	}
	view, err := s.view(ctx, a, v)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	return view, nil
}

func (s *ActionService) writeErr(ctx context.Context, err error) error {
	switch {
	case errors.Is(err, ErrStale):
		return apierr.New(ctx, connect.CodeAborted, apierr.ReasonInvalidArgument,
			"This action changed since you opened it. Open it again to see where it stands.")
	case err != nil:
		return s.ops.internal(ctx, err)
	}
	return nil
}

// GetActionOptions returns what a new action may name.
func (s *ActionService) GetActionOptions(
	ctx context.Context, request *connect.Request[clustersv1.GetActionOptionsRequest],
) (*connect.Response[clustersv1.GetActionOptionsResponse], error) {
	clusterID := request.Msg.GetClusterId()
	if _, err := s.ops.access(ctx, clusterID); err != nil {
		return nil, err
	}
	out := &clustersv1.GetActionOptionsResponse{}
	for _, c := range supportKinds {
		out.SupportKinds = append(out.SupportKinds, &clustersv1.Choice{Value: c.Value, Label: c.Label})
	}
	for _, c := range actionSources {
		out.Sources = append(out.Sources, &clustersv1.Choice{Value: c.Value, Label: c.Label})
	}
	courses, err := s.ops.ops.Courses(ctx)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	for _, c := range courses {
		out.Courses = append(out.Courses, &clustersv1.Choice{Value: c.ID, Label: c.Name})
	}
	members, _, err := s.ops.data.MemberSchools(ctx, clusterID, "", maxSchoolsOnce, 0)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	for _, m := range members {
		out.Schools = append(out.Schools, &clustersv1.Choice{Value: m.ID, Label: m.Name + " · " + m.SchoolID})
	}
	past, err := s.ops.data.PastActivities(ctx, clusterID, s.ops.today(), maxPageSize)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	upcoming, err := s.ops.data.UpcomingActivities(ctx, clusterID, s.ops.today(), maxPageSize)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	for _, a := range append(past, upcoming...) {
		view := toActivity(a)
		out.Meetings = append(out.Meetings, &clustersv1.Choice{Value: "activity:" + a.ID, Label: view.GetName() + " · " + view.GetDate()})
	}
	plans, err := s.ops.ops.Plans(ctx, clusterID)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	for _, p := range plans {
		if p.ActivityID == "" && p.Status != "cancelled" {
			out.Meetings = append(out.Meetings, &clustersv1.Choice{Value: "plan:" + p.ID, Label: p.Title + " · " + p.PlannedOn.Format(isoDate) + " (planned)"})
		}
	}
	return connect.NewResponse(out), nil
}

// ListActions is the leader's register (or the cluster's, for its staff).
func (s *ActionService) ListActions(
	ctx context.Context, request *connect.Request[clustersv1.ListActionsRequest],
) (*connect.Response[clustersv1.ListActionsResponse], error) {
	msg := request.Msg
	who, err := s.ops.access(ctx, msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	tab := msg.GetTab()
	if tab == "" {
		tab = "open"
	}
	if !slices.Contains([]string{"open", "waiting", "completed"}, tab) {
		return nil, invalid(ctx, "Choose Open, Waiting or Completed.")
	}
	actions, err := s.store.ClusterActions(ctx, msg.GetClusterId(), maxActionsListed)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	v := actionViewer{principal: who.principal, isLeader: who.isLeader, own: ownIDs(who.principal), managesCluster: !who.isLeader}
	out := &clustersv1.ListActionsResponse{Counts: map[string]int32{}}
	var cards []*clustersv1.ActionCard
	for _, a := range actions {
		// A leader sees the cluster's register; drafts are their author's.
		if a.Status == "draft" && a.CreatedBy != who.principal.UserID {
			continue
		}
		t := actionTab(a.Status, s.progresses(a))
		out.Counts[t]++
		if t == tab {
			cards = append(cards, s.card(a, v))
		}
	}
	sortCards(cards)
	page, size, err := pageOf(ctx, msg.GetPage())
	if err != nil {
		return nil, err
	}
	start := min(int((page-1)*size), len(cards))
	end := min(start+int(size), len(cards))
	out.Actions = cards[start:end]
	out.Page = pageInfo(page, size, int64(len(cards)))
	return connect.NewResponse(out), nil
}

// GetAction returns one action for the caller.
func (s *ActionService) GetAction(
	ctx context.Context, request *connect.Request[clustersv1.GetActionRequest],
) (*connect.Response[clustersv1.GetActionResponse], error) {
	view, err := s.reload(ctx, request.Msg.GetId())
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.GetActionResponse{Action: view}), nil
}

// SaveAction creates or edits the leader's draft and, with submit, sends it:
// each school is routed to the CCEO holding it, and they are told.
func (s *ActionService) SaveAction(
	ctx context.Context, request *connect.Request[clustersv1.SaveActionRequest],
) (*connect.Response[clustersv1.SaveActionResponse], error) {
	msg := request.Msg
	who, err := s.ops.leaderOf(ctx, msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	key := strings.TrimSpace(msg.GetIdempotencyKey())
	if len(key) > maxIdempotencyLength {
		return nil, invalid(ctx, "The submission key is too long.")
	}
	if key != "" && msg.GetId() == "" {
		// A retried submission returns what the first one made.
		if existing, err := s.store.ActionByKey(ctx, key); err == nil {
			if existing.CreatedBy != who.principal.UserID || existing.ClusterID != msg.GetClusterId() {
				return nil, invalid(ctx, "That submission key belongs to another action.")
			}
			view, err := s.reload(ctx, existing.ID)
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(&clustersv1.SaveActionResponse{Action: view, Replayed: true}), nil
		} else if !errors.Is(err, ErrNotFound) {
			return nil, s.ops.internal(ctx, err)
		}
	}
	draft, err := s.actionFrom(ctx, msg)
	if err != nil {
		return nil, err
	}
	isNew := msg.GetId() == ""
	write := ActionWrite{ActorID: who.principal.UserID, ActorRole: who.principal.ActiveRole}
	if isNew {
		if draft.ID, err = newID(); err != nil {
			return nil, s.ops.internal(ctx, err)
		}
		if draft.Ref, err = newRef(); err != nil {
			return nil, s.ops.internal(ctx, err)
		}
		_, _, year := fiscalYear(s.ops.today())
		draft.FiscalYear = int32(year) // #nosec G115 -- a year
		write.Events = []ActionEventRecord{{Event: "drafted"}}
	} else {
		existing, _, err := s.load(ctx, msg.GetId())
		if err != nil {
			return nil, err
		}
		if existing.ClusterID != msg.GetClusterId() || existing.CreatedBy != who.principal.UserID || existing.Status != "draft" {
			return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
				"Only your own draft can be edited. A sent action is answered with Reply.")
		}
		draft.ID, draft.Ref, draft.Version = existing.ID, existing.Ref, msg.GetVersion()
		write.Events = []ActionEventRecord{{Event: "edited"}}
	}
	err = s.store.SaveActionDraft(ctx, draft, key, isNew, write)
	if errors.Is(err, ErrAlreadyAssigned) {
		return nil, apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument, "That submission was already saved.")
	}
	if err := s.writeErr(ctx, err); err != nil {
		return nil, err
	}
	if msg.GetSubmit() {
		if err := s.submit(ctx, draft.ID, who); err != nil {
			return nil, err
		}
	}
	view, err := s.reload(ctx, draft.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.SaveActionResponse{Action: view}), nil
}

// actionFrom checks an action's fields (brief 3.3: schools, the support
// needed, a description and a target date are required).
func (s *ActionService) actionFrom(ctx context.Context, msg *clustersv1.SaveActionRequest) (ActionRecord, error) {
	a := ActionRecord{ClusterID: msg.GetClusterId(), Source: msg.GetSource(), SupportKind: msg.GetSupportKind(),
		Priority: msg.GetPriority(), SourceActivityID: msg.GetSourceActivityId(), SourcePlanID: msg.GetSourcePlanId()}
	if a.Source == "" {
		a.Source = "observation"
	}
	if a.Priority == "" {
		a.Priority = "normal"
	}
	switch {
	case !validChoice(actionSources, a.Source):
		return a, invalid(ctx, "Say where the need was raised.")
	case !validChoice(supportKinds, a.SupportKind):
		return a, invalid(ctx, "Choose what support is needed.")
	case !slices.Contains([]string{"normal", "high", "urgent"}, a.Priority):
		return a, invalid(ctx, "The priority is normal, high or urgent.")
	}
	if a.Source == "meeting" {
		if (a.SourceActivityID == "") == (a.SourcePlanID == "") {
			return a, invalid(ctx, "Choose the meeting the need was raised at.")
		}
		if a.SourceActivityID != "" {
			activity, err := s.ops.ops.ActivityFor(ctx, a.SourceActivityID)
			if err != nil || activity.ClusterID != a.ClusterID {
				return a, invalid(ctx, "Choose one of this cluster's meetings.")
			}
		} else {
			plan, err := s.ops.ops.Plan(ctx, a.SourcePlanID)
			if err != nil || plan.ClusterID != a.ClusterID {
				return a, invalid(ctx, "Choose one of this cluster's meetings.")
			}
		}
	} else {
		// No meeting is made up for a need raised outside one.
		a.SourceActivityID, a.SourcePlanID = "", ""
	}
	if a.SupportKind == "training" {
		courses, err := s.ops.ops.Courses(ctx)
		if err != nil {
			return a, s.ops.internal(ctx, err)
		}
		course := msg.GetTrainingCourseId()
		if course != "" && !slices.ContainsFunc(courses, func(c Course) bool { return c.ID == course }) {
			return a, invalid(ctx, "Choose one of the governed training topics.")
		}
		a.TrainingCourseID = course
	}
	var err error
	if a.Description, err = textOf(ctx, "A brief description", msg.GetDescription(), maxTextLength, true); err != nil {
		return a, err
	}
	if a.ExpectedOutcome, err = textOf(ctx, "The expected outcome", msg.GetExpectedOutcome(), maxTextLength, false); err != nil {
		return a, err
	}
	if a.Title, err = textOf(ctx, "The title", msg.GetTitle(), maxTitleLength, false); err != nil {
		return a, err
	}
	if a.Title == "" {
		a.Title = labelIn(supportKinds, a.SupportKind)
	}
	target, err := time.Parse(isoDate, msg.GetTargetOn())
	if err != nil {
		return a, invalid(ctx, "Choose the target date.")
	}
	if target.Before(s.ops.today()) {
		return a, invalid(ctx, "The target date cannot be in the past.")
	}
	a.TargetOn = target
	wanted := slices.Compact(slices.Sorted(slices.Values(msg.GetSchoolIds())))
	if len(wanted) == 0 || len(wanted) > maxSchoolsPerAction {
		return a, invalid(ctx, "Choose between 1 and 100 member schools.")
	}
	members, err := s.ops.memberSchoolsOnly(ctx, a.ClusterID, wanted)
	if err != nil {
		return a, err
	}
	a.SchoolIDs = members
	return a, nil
}

// submit routes a saved draft's schools and tells each routed person.
func (s *ActionService) submit(ctx context.Context, id string, who side) error {
	a, err := s.store.Action(ctx, id)
	if err != nil {
		return s.ops.internal(ctx, err)
	}
	routes, err := s.store.Routes(ctx, a.ClusterID, a.SchoolIDs)
	if err != nil {
		return s.ops.internal(ctx, err)
	}
	ids := make([]string, len(a.SchoolIDs))
	for i := range ids {
		if ids[i], err = newID(); err != nil {
			return s.ops.internal(ctx, err)
		}
	}
	write := ActionWrite{ActorID: who.principal.UserID, ActorRole: who.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: "submitted", ToStatus: schoolAwaiting}}}
	names := map[string]string{}
	members, _, err := s.ops.data.MemberSchools(ctx, a.ClusterID, "", maxSchoolsOnce, 0)
	if err != nil {
		return s.ops.internal(ctx, err)
	}
	for _, m := range members {
		names[m.ID] = m.Name
	}
	for _, school := range a.SchoolIDs {
		r := routes[school]
		note := map[string]string{"owner": "To the CCEO holding the school.",
			"supervisor": "Nobody holds the school: to the supervising Program Lead to assign.",
			"unassigned": "Nobody holds the school and no supervisor is known: waiting for assignment."}[r.RoutedTo]
		write.Events = append(write.Events, ActionEventRecord{Event: "routed", School: school, Note: note})
		recipient := r.ResponsibleStaffID
		if recipient == "" {
			recipient = r.SupervisorStaffID
		}
		if recipient == "" {
			continue
		}
		user, err := s.store.UserOfStaff(ctx, recipient)
		if err != nil {
			return s.ops.internal(ctx, err)
		}
		if user == "" {
			continue
		}
		write.Notices = append(write.Notices, NoticeRecord{
			RecipientUserID: user, Event: "cluster_action_submitted", SenderUserID: who.principal.UserID,
			Title: "New Cluster Support Request",
			Body: fmt.Sprintf("%s: your Cluster Leader has requested %s for %s by %s (%s). Please review the request in Cluster Support Requests.",
				a.ClusterName, strings.ToLower(labelIn(supportKinds, a.SupportKind)), names[school], a.TargetOn.Format("2 Jan 2006"), a.Ref),
			TargetRoute: "/clusters/" + a.ClusterID,
			DedupKey:    fmt.Sprintf("submitted:%s:%s:%s", a.ID, school, user),
		})
	}
	return s.writeErr(ctx, s.store.SubmitAction(ctx, a.ID, a.Version, routes, a.SchoolIDs, ids, write))
}

// leaderNotices tells the action's author (and the cluster's live leaders)
// about a staff response.
func (s *ActionService) leaderNotices(ctx context.Context, a ActionRecord, event, title, body, key string, sender string) ([]NoticeRecord, error) {
	leaders, err := s.store.LeadersOf(ctx, a.ClusterID, s.ops.today())
	if err != nil {
		return nil, err
	}
	recipients := []string{a.CreatedBy}
	for _, l := range leaders {
		if !slices.Contains(recipients, l) {
			recipients = append(recipients, l)
		}
	}
	var out []NoticeRecord
	for _, user := range recipients {
		out = append(out, NoticeRecord{RecipientUserID: user, Event: event, Title: title, Body: body, SenderUserID: sender,
			TargetRoute: "/clusters/" + a.ClusterID, DedupKey: key + ":" + user})
	}
	return out, nil
}

// ReplyToAction is the leader answering a clarification or revising a
// returned school: the request goes back to its staff for review.
func (s *ActionService) ReplyToAction(
	ctx context.Context, request *connect.Request[clustersv1.ReplyToActionRequest],
) (*connect.Response[clustersv1.ReplyToActionResponse], error) {
	msg := request.Msg
	a, v, err := s.load(ctx, msg.GetId())
	if err != nil {
		return nil, err
	}
	if !v.isLeader {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, "Only the cluster's leader replies.")
	}
	note, err := textOf(ctx, "Your reply", msg.GetNote(), maxTextLength, true)
	if err != nil {
		return nil, err
	}
	replied := 0
	for _, r := range a.Schools {
		if (msg.GetSchoolId() != "" && r.SchoolID != msg.GetSchoolId()) || (r.Status != schoolClarification && r.Status != schoolReturned) {
			continue
		}
		write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
			Events: []ActionEventRecord{{Event: "replied", School: r.SchoolID, FromStatus: r.Status, ToStatus: schoolAwaiting, Note: note}}}
		if user := firstNonEmpty(r.ResponsibleUserID, r.SupervisorUserID); user != "" {
			write.Notices = []NoticeRecord{{RecipientUserID: user, Event: "cluster_action_replied", SenderUserID: v.principal.UserID,
				Title: "Cluster Leader replied", TargetRoute: "/clusters/" + a.ClusterID,
				Body:     fmt.Sprintf("%s (%s, %s): %s", a.Title, r.Name, a.Ref, note),
				DedupKey: fmt.Sprintf("replied:%s:%s:%d", a.ID, r.SchoolID, time.Now().UnixNano())}}
		}
		if err := s.store.MoveSchool(ctx, a.ID, r.SchoolID, []string{schoolClarification, schoolReturned}, schoolAwaiting, note, write); err != nil {
			return nil, s.writeErr(ctx, err)
		}
		replied++
	}
	if replied == 0 {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "No school is waiting for your reply.")
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.ReplyToActionResponse{Action: view}), nil
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

// CancelAction cancels the leader's action, with a reason; schools whose
// support is already planned keep their link and history.
func (s *ActionService) CancelAction(
	ctx context.Context, request *connect.Request[clustersv1.CancelActionRequest],
) (*connect.Response[clustersv1.CancelActionResponse], error) {
	a, v, err := s.load(ctx, request.Msg.GetId())
	if err != nil {
		return nil, err
	}
	if !v.isLeader || (a.Status != "draft" && a.Status != "submitted") {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "Only an open action of yours can be cancelled.")
	}
	reason, err := textOf(ctx, "The reason", request.Msg.GetReason(), maxReasonLength, true)
	if err != nil {
		return nil, err
	}
	write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: "cancelled", FromStatus: a.Status, ToStatus: "cancelled", Note: reason}}}
	for _, r := range a.Schools {
		if user := firstNonEmpty(r.ResponsibleUserID, r.SupervisorUserID); user != "" && !finished(s.progressOf(r)) {
			write.Notices = append(write.Notices, NoticeRecord{RecipientUserID: user, Event: "cluster_action_cancelled",
				SenderUserID: v.principal.UserID, Title: "Cluster Support Request cancelled", TargetRoute: "/clusters/" + a.ClusterID,
				Body:     fmt.Sprintf("%s (%s, %s) was cancelled by the Cluster Leader: %s", a.Title, r.Name, a.Ref, reason),
				DedupKey: fmt.Sprintf("cancelled:%s:%s", a.ID, user)})
		}
	}
	if err := s.writeErr(ctx, s.store.EndAction(ctx, a.ID, "cancelled", reason, write)); err != nil {
		return nil, err
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.CancelActionResponse{Action: view}), nil
}

// CloseAction closes an action once every school is verified, returned,
// declined or cancelled; never because a date passed.
func (s *ActionService) CloseAction(
	ctx context.Context, request *connect.Request[clustersv1.CloseActionRequest],
) (*connect.Response[clustersv1.CloseActionResponse], error) {
	a, v, err := s.load(ctx, request.Msg.GetId())
	if err != nil {
		return nil, err
	}
	key, _, _, _ := actionOverall(a.Status, s.progresses(a))
	if !v.isLeader || key != "review_due" {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"An action closes once every school's support is verified, or returned, declined or cancelled.")
	}
	summary, err := textOf(ctx, "The closing summary", request.Msg.GetSummary(), maxTextLength, true)
	if err != nil {
		return nil, err
	}
	write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: "closed", FromStatus: a.Status, ToStatus: "closed", Note: summary}}}
	if err := s.writeErr(ctx, s.store.EndAction(ctx, a.ID, "closed", summary, write)); err != nil {
		return nil, err
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.CloseActionResponse{Action: view}), nil
}

// ReviewAction records a meeting's review of an earlier action, linked to
// it, never copied (brief 9.2).
func (s *ActionService) ReviewAction(
	ctx context.Context, request *connect.Request[clustersv1.ReviewActionRequest],
) (*connect.Response[clustersv1.ReviewActionResponse], error) {
	msg := request.Msg
	a, v, err := s.load(ctx, msg.GetId())
	if err != nil {
		return nil, err
	}
	if !v.isLeader || a.Status != "submitted" {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "Only a sent, open action is reviewed.")
	}
	outcome := msg.GetOutcome()
	if !slices.Contains([]string{"continue", "escalate", "propose_closure"}, outcome) {
		return nil, invalid(ctx, "Say what the meeting agreed: continue, escalate or propose closure.")
	}
	if msg.GetMeetingActivityId() != "" {
		if activity, err := s.ops.ops.ActivityFor(ctx, msg.GetMeetingActivityId()); err != nil || activity.ClusterID != a.ClusterID {
			return nil, invalid(ctx, "Choose one of this cluster's meetings.")
		}
	}
	if msg.GetMeetingPlanId() != "" {
		if plan, err := s.ops.ops.Plan(ctx, msg.GetMeetingPlanId()); err != nil || plan.ClusterID != a.ClusterID {
			return nil, invalid(ctx, "Choose one of this cluster's meetings.")
		}
	}
	r := ReviewRecord{Outcome: outcome}
	for _, field := range []struct {
		what string
		raw  string
		into *string
	}{
		{"The progress discussed", msg.GetProgress(), &r.Progress},
		{"The challenges", msg.GetChallenges(), &r.Challenges},
		{"The agreed next step", msg.GetNextStep(), &r.NextStep},
	} {
		if *field.into, err = textOf(ctx, field.what, field.raw, maxTextLength, false); err != nil {
			return nil, err
		}
	}
	if r.Progress == "" && r.NextStep == "" {
		return nil, invalid(ctx, "Write the progress discussed or the agreed next step.")
	}
	if r.ID, err = newID(); err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	write := ActionWrite{ActorID: v.principal.UserID, ActorRole: v.principal.ActiveRole,
		Events: []ActionEventRecord{{Event: "reviewed", Note: firstNonEmpty(r.NextStep, r.Progress)}}}
	if err := s.writeErr(ctx, s.store.AddReview(ctx, r, a.ID, msg.GetMeetingActivityId(), msg.GetMeetingPlanId(), write)); err != nil {
		return nil, err
	}
	if outcome == "escalate" {
		if err := s.escalate(ctx, a, v, "", "Agreed at a cluster meeting: "+firstNonEmpty(r.Challenges, r.NextStep, r.Progress), "leader"); err != nil {
			return nil, err
		}
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.ReviewActionResponse{Action: view}), nil
}

// EscalateAction raises an unresolved action to the supervising Program Lead.
func (s *ActionService) EscalateAction(
	ctx context.Context, request *connect.Request[clustersv1.EscalateActionRequest],
) (*connect.Response[clustersv1.EscalateActionResponse], error) {
	a, v, err := s.load(ctx, request.Msg.GetId())
	if err != nil {
		return nil, err
	}
	if !v.isLeader || a.Status != "submitted" {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "Only an open action of yours is escalated.")
	}
	reason, err := textOf(ctx, "The reason", request.Msg.GetReason(), maxReasonLength, true)
	if err != nil {
		return nil, err
	}
	if err := s.escalate(ctx, a, v, request.Msg.GetSchoolId(), reason, "leader"); err != nil {
		return nil, err
	}
	view, err := s.reload(ctx, a.ID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.EscalateActionResponse{Action: view}), nil
}

// escalate raises the action (or one school) one step up the reporting line:
// from the responsible CCEO to their supervisor. It never changes who holds
// the school.
func (s *ActionService) escalate(ctx context.Context, a ActionRecord, v actionViewer, schoolID, reason, kind string) error {
	targets := map[string]string{} // supervisor staff id -> responsible staff id
	for _, r := range a.Schools {
		if (schoolID != "" && r.SchoolID != schoolID) || finished(s.progressOf(r)) {
			continue
		}
		to := r.SupervisorStaffID
		if to == "" && r.ResponsibleStaffID != "" {
			supervisor, err := s.store.SupervisorOf(ctx, r.ResponsibleStaffID)
			if err != nil {
				return s.ops.internal(ctx, err)
			}
			to = supervisor
		}
		if to != "" {
			targets[to] = r.ResponsibleStaffID
		}
	}
	if len(targets) == 0 {
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"No supervisor is known for these schools' staff. Ask the Country Director's office.")
	}
	actor := v.principal.UserID
	if kind == "policy" {
		actor = "system"
	}
	for to, from := range targets {
		id, err := newID()
		if err != nil {
			return s.ops.internal(ctx, err)
		}
		write := ActionWrite{ActorID: actor, ActorRole: v.principal.ActiveRole,
			Events: []ActionEventRecord{{Event: "escalated", School: schoolID, Note: reason}}}
		if user, err := s.store.UserOfStaff(ctx, to); err == nil && user != "" {
			write.Notices = []NoticeRecord{{RecipientUserID: user, Event: "cluster_action_escalated", SenderUserID: v.principal.UserID,
				Title: "Cluster Support Request escalated to you", TargetRoute: "/clusters/" + a.ClusterID,
				Body:     fmt.Sprintf("%s (%s, %s): %s", a.Title, a.ClusterName, a.Ref, reason),
				DedupKey: fmt.Sprintf("escalated:%s:%s:%s", a.ID, to, id)}}
		}
		if err := s.store.AddEscalation(ctx, EscalationRecord{ID: id, SchoolID: schoolID, Reason: reason, ToStaffID: to},
			a.ID, kind, from, write); err != nil {
			return s.writeErr(ctx, err)
		}
	}
	return nil
}

// ListCarryForward is the cluster's unfinished actions, oldest target
// first, to bring to the next meeting (brief 9.1).
func (s *ActionService) ListCarryForward(
	ctx context.Context, request *connect.Request[clustersv1.ListCarryForwardRequest],
) (*connect.Response[clustersv1.ListCarryForwardResponse], error) {
	who, err := s.ops.access(ctx, request.Msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	actions, err := s.store.ClusterActions(ctx, request.Msg.GetClusterId(), maxActionsListed)
	if err != nil {
		return nil, s.ops.internal(ctx, err)
	}
	v := actionViewer{principal: who.principal, isLeader: who.isLeader, own: ownIDs(who.principal), managesCluster: !who.isLeader}
	out := &clustersv1.ListCarryForwardResponse{}
	for _, a := range actions {
		if a.Status == "submitted" {
			out.Actions = append(out.Actions, s.card(a, v))
		}
	}
	sortCards(out.Actions)
	return connect.NewResponse(out), nil
}
