package clusterlead

import (
	"context"
	"errors"
	"slices"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// A leader's meeting plan (brief A4): Draft → Submitted → Approved or
// Returned → Scheduled. Scheduling is the existing application's: staff
// schedule the activity there, under its own calendar, permission and
// fiscal-year rules, and link the approved plan to it. From then on the
// official activity's own statuses (started, evidence, verified) apply; the
// plan never becomes a second official record.

var planCategories = map[string]bool{"only_meeting": true, "cluster_leaders": true, "training": true}

const maxParticipants = 10000

// ListPlans returns the cluster's plans for its leader or its staff.
func (o *OperationsService) ListPlans(
	ctx context.Context, request *connect.Request[clustersv1.ListPlansRequest],
) (*connect.Response[clustersv1.ListPlansResponse], error) {
	clusterID := request.Msg.GetClusterId()
	who, err := o.access(ctx, clusterID)
	if err != nil {
		return nil, err
	}
	plans, err := o.ops.Plans(ctx, clusterID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	response := &clustersv1.ListPlansResponse{}
	linked := map[string]bool{}
	for _, plan := range plans {
		response.Plans = append(response.Plans, toPlan(plan, who))
		if plan.ActivityID != "" {
			linked[plan.ActivityID] = true
		}
	}
	if !who.isLeader {
		upcoming, err := o.data.UpcomingActivities(ctx, clusterID, o.today(), maxPageSize)
		if err != nil {
			return nil, o.internal(ctx, err)
		}
		for _, activity := range upcoming {
			if !linked[activity.ID] {
				out := toActivity(activity)
				response.LinkableActivities = append(response.LinkableActivities, &clustersv1.ActivityChoice{
					Id: activity.ID, Label: out.GetName() + " · " + out.GetType(), Date: out.GetDate(),
				})
			}
		}
	}
	return connect.NewResponse(response), nil
}

// GetPlanOptions returns the courses a cluster training may deliver.
func (o *OperationsService) GetPlanOptions(
	ctx context.Context, _ *connect.Request[clustersv1.GetPlanOptionsRequest],
) (*connect.Response[clustersv1.GetPlanOptionsResponse], error) {
	if _, err := principalOf(ctx); err != nil {
		return nil, err
	}
	if err := o.checkReady(ctx); err != nil {
		return nil, err
	}
	courses, err := o.ops.Courses(ctx)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	response := &clustersv1.GetPlanOptionsResponse{}
	for _, c := range courses {
		response.Courses = append(response.Courses, &clustersv1.CourseChoice{
			Id: c.ID, Name: c.Name, Category: c.Category, Intervention: c.Intervention,
		})
	}
	return connect.NewResponse(response), nil
}

// SavePlan creates or edits the leader's plan while it is still planned;
// saving with submit sends it (back) to staff for review.
func (o *OperationsService) SavePlan(
	ctx context.Context, request *connect.Request[clustersv1.SavePlanRequest],
) (*connect.Response[clustersv1.SavePlanResponse], error) {
	msg := request.Msg
	who, err := o.leaderOf(ctx, msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	plan, err := o.planFrom(ctx, msg)
	if err != nil {
		return nil, err
	}
	isNew := msg.GetId() == ""
	if isNew {
		if plan.ID, err = newID(); err != nil {
			return nil, o.internal(ctx, err)
		}
	} else {
		existing, err := o.ops.Plan(ctx, msg.GetId())
		if errors.Is(err, ErrNotFound) || (err == nil && existing.ClusterID != msg.GetClusterId()) {
			return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such plan in this cluster.")
		}
		if err != nil {
			return nil, o.internal(ctx, err)
		}
		plan.ID = existing.ID
	}
	plan.Status, plan.ClusterID = "draft", msg.GetClusterId()
	event := map[bool]string{true: "drafted", false: "edited"}[isNew]
	if msg.GetSubmit() {
		plan.Status, event = "submitted", "submitted"
	}
	if err := o.ops.SavePlan(ctx, plan, isNew, who.principal.UserID, event); err != nil {
		if errors.Is(err, ErrNotLive) {
			return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
				"Only a draft or returned plan can be changed.")
		}
		return nil, o.internal(ctx, err)
	}
	return o.planResponse(ctx, plan.ID, who, func(p *clustersv1.MeetingPlan) *clustersv1.SavePlanResponse {
		return &clustersv1.SavePlanResponse{Plan: p}
	})
}

// planFrom checks a plan's fields (brief A4: a training names a governed
// course; a meeting shows no training fields).
func (o *OperationsService) planFrom(ctx context.Context, msg *clustersv1.SavePlanRequest) (Plan, error) {
	category := msg.GetCategory()
	if !planCategories[category] {
		return Plan{}, invalid(ctx, "Choose a meeting, a cluster leaders' meeting or a cluster training.")
	}
	title, err := textOf(ctx, "A title", msg.GetTitle(), maxTitleLength, true)
	if err != nil {
		return Plan{}, err
	}
	plannedOn, err := time.Parse(isoDate, msg.GetPlannedOn())
	if err != nil {
		return Plan{}, invalid(ctx, "The planned date must be a date (YYYY-MM-DD).")
	}
	if plannedOn.Before(o.today()) {
		return Plan{}, invalid(ctx, "The planned date cannot be in the past.")
	}
	course := msg.GetTrainingCourseId()
	if category == "training" {
		courses, err := o.ops.Courses(ctx)
		if err != nil {
			return Plan{}, o.internal(ctx, err)
		}
		if !slices.ContainsFunc(courses, func(c Course) bool { return c.ID == course }) {
			return Plan{}, invalid(ctx, "A cluster training names one of the courses a cluster may receive.")
		}
	} else if course != "" {
		return Plan{}, invalid(ctx, "A meeting names no training course.")
	}
	if msg.GetExpectedParticipants() < 0 || msg.GetExpectedParticipants() > maxParticipants {
		return Plan{}, invalid(ctx, "Expected participants must be between 0 and 10000.")
	}
	plan := Plan{Category: category, Title: title, TrainingCourseID: course, PlannedOn: plannedOn,
		IsOnline: msg.GetIsOnline(), ExpectedParticipants: msg.GetExpectedParticipants()}
	for _, field := range []struct {
		what  string
		raw   string
		limit int
		into  *string
	}{
		{"The start time", msg.GetStartsAt(), maxTitleLength, &plan.StartsAt},
		{"The venue", msg.GetVenue(), maxTitleLength, &plan.Venue},
		{"The objectives", msg.GetObjectives(), maxTextLength, &plan.Objectives},
		{"The agenda", msg.GetAgenda(), maxTextLength, &plan.Agenda},
		{"The facilitator", msg.GetFacilitator(), maxTitleLength, &plan.Facilitator},
		{"The resources", msg.GetResources(), maxTextLength, &plan.Resources},
		{"The notes", msg.GetNotes(), maxTextLength, &plan.Notes},
	} {
		if *field.into, err = textOf(ctx, field.what, field.raw, field.limit, false); err != nil {
			return Plan{}, err
		}
	}
	return plan, nil
}

// CancelPlan cancels the leader's plan before it is scheduled.
func (o *OperationsService) CancelPlan(
	ctx context.Context, request *connect.Request[clustersv1.CancelPlanRequest],
) (*connect.Response[clustersv1.CancelPlanResponse], error) {
	plan, who, err := o.planFor(ctx, request.Msg.GetId(), o.leaderOf)
	if err != nil {
		return nil, err
	}
	reason, err := textOf(ctx, "The reason", request.Msg.GetReason(), maxReasonLength, false)
	if err != nil {
		return nil, err
	}
	if err := o.move(ctx, plan.ID, livePlanStatuses, "cancelled", who, reason, ""); err != nil {
		return nil, err
	}
	return o.planResponse(ctx, plan.ID, who, func(p *clustersv1.MeetingPlan) *clustersv1.CancelPlanResponse {
		return &clustersv1.CancelPlanResponse{Plan: p}
	})
}

// ReviewPlan approves or returns a submitted plan (staff only).
func (o *OperationsService) ReviewPlan(
	ctx context.Context, request *connect.Request[clustersv1.ReviewPlanRequest],
) (*connect.Response[clustersv1.ReviewPlanResponse], error) {
	plan, who, err := o.planFor(ctx, request.Msg.GetId(), o.staffOf)
	if err != nil {
		return nil, err
	}
	note, err := textOf(ctx, "The note", request.Msg.GetNote(), maxReasonLength, !request.Msg.GetApprove())
	if err != nil {
		return nil, err
	}
	status := map[bool]string{true: "approved", false: "returned"}[request.Msg.GetApprove()]
	if err := o.move(ctx, plan.ID, []string{"submitted"}, status, who, note, ""); err != nil {
		return nil, err
	}
	return o.planResponse(ctx, plan.ID, who, func(p *clustersv1.MeetingPlan) *clustersv1.ReviewPlanResponse {
		return &clustersv1.ReviewPlanResponse{Plan: p}
	})
}

// LinkPlan links an approved plan to the activity staff scheduled for it.
func (o *OperationsService) LinkPlan(
	ctx context.Context, request *connect.Request[clustersv1.LinkPlanRequest],
) (*connect.Response[clustersv1.LinkPlanResponse], error) {
	plan, who, err := o.planFor(ctx, request.Msg.GetId(), o.staffOf)
	if err != nil {
		return nil, err
	}
	activity, err := o.ops.ActivityFor(ctx, request.Msg.GetActivityId())
	if errors.Is(err, ErrNotFound) || (err == nil && activity.ClusterID != plan.ClusterID) {
		return nil, invalid(ctx, "Choose a scheduled activity of this cluster.")
	}
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	if !slices.Contains(plannedStatuses, activity.Status) {
		return nil, invalid(ctx, "The activity is no longer planned.")
	}
	if (plan.Category == "training") != (activity.Kind == "training") {
		return nil, invalid(ctx, "A training plan links to a training activity, a meeting plan to a meeting.")
	}
	if err := o.move(ctx, plan.ID, []string{"approved"}, "scheduled", who, "", activity.ID); err != nil {
		return nil, err
	}
	return o.planResponse(ctx, plan.ID, who, func(p *clustersv1.MeetingPlan) *clustersv1.LinkPlanResponse {
		return &clustersv1.LinkPlanResponse{Plan: p}
	})
}

// livePlanStatuses: a plan the leader may still invite schools to or cancel.
var livePlanStatuses = []string{"draft", "submitted", "returned", "approved"}

// GetPlan returns a plan with the member schools invited to it.
func (o *OperationsService) GetPlan(
	ctx context.Context, request *connect.Request[clustersv1.GetPlanRequest],
) (*connect.Response[clustersv1.GetPlanResponse], error) {
	plan, who, err := o.planFor(ctx, request.Msg.GetId(), o.access)
	if err != nil {
		return nil, err
	}
	invitees, err := o.ops.PlanInvitees(ctx, plan.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	response := &clustersv1.GetPlanResponse{Plan: toPlan(plan, who), CanInvite: o.canInvitePlan(plan, who)}
	for _, i := range invitees {
		response.Invited = append(response.Invited, &clustersv1.PlanInvitee{SchoolId: i.SchoolID, EdifySchoolId: i.EdifySchoolID,
			Name: i.Name, Channel: i.Channel, InvitedOn: i.InvitedAt.In(o.location).Format(isoDate)})
	}
	return connect.NewResponse(response), nil
}

// InvitePlanSchools records the leader's invitations to a planned meeting
// or training; they carry over to its activity once staff link it.
func (o *OperationsService) InvitePlanSchools(
	ctx context.Context, request *connect.Request[clustersv1.InvitePlanSchoolsRequest],
) (*connect.Response[clustersv1.InvitePlanSchoolsResponse], error) {
	plan, who, err := o.planFor(ctx, request.Msg.GetPlanId(), o.access)
	if err != nil {
		return nil, err
	}
	if !who.isLeader {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, "Only the cluster's leader mobilises its schools.")
	}
	if !o.canInvitePlan(plan, who) {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"Schools are invited to a plan that is still planned: not cancelled, not yet scheduled, not past.")
	}
	channel := request.Msg.GetChannel()
	if !channels[channel] {
		return nil, invalid(ctx, "Say how the schools were invited: in person, phone, SMS, email or WhatsApp.")
	}
	wanted, err := o.memberSchoolsOnly(ctx, plan.ClusterID, request.Msg.GetSchoolIds())
	if err != nil {
		return nil, err
	}
	ids := make([]string, len(wanted))
	for i := range ids {
		if ids[i], err = newID(); err != nil {
			return nil, o.internal(ctx, err)
		}
	}
	invited, err := o.ops.InvitePlan(ctx, plan.ClusterID, plan.ID, wanted, ids, channel, who.principal.UserID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.InvitePlanSchoolsResponse{
		Invited: int32(invited), AlreadyInvited: int32(len(wanted) - invited), // #nosec G115 -- at most maxSchoolsOnce
	}), nil
}

func (o *OperationsService) canInvitePlan(p Plan, who side) bool {
	return who.isLeader && slices.Contains(livePlanStatuses, p.Status) && !p.PlannedOn.Before(o.today())
}

// planFor is a plan and the caller's side of its cluster, by allowed().
func (o *OperationsService) planFor(
	ctx context.Context, id string, allowed func(context.Context, string) (side, error),
) (Plan, side, error) {
	if err := validID(ctx, "plan", id); err != nil {
		return Plan{}, side{}, err
	}
	if _, err := principalOf(ctx); err != nil {
		return Plan{}, side{}, err
	}
	plan, err := o.ops.Plan(ctx, id)
	if errors.Is(err, ErrNotFound) {
		return Plan{}, side{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such plan.")
	}
	if err != nil {
		return Plan{}, side{}, o.internal(ctx, err)
	}
	who, err := allowed(ctx, plan.ClusterID)
	return plan, who, err
}

func (o *OperationsService) move(ctx context.Context, id string, from []string, status string, who side, note, activityID string) error {
	err := o.ops.MovePlan(ctx, id, from, status, status, who.principal.UserID, note, activityID)
	switch {
	case errors.Is(err, ErrNotLive):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"The plan has moved on since you opened it.")
	case errors.Is(err, ErrAlreadyAssigned):
		return apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument,
			"That activity is already linked to another plan.")
	case err != nil:
		return o.internal(ctx, err)
	}
	return nil
}

func (o *OperationsService) planResponse[T any](
	ctx context.Context, id string, who side, wrap func(*clustersv1.MeetingPlan) *T,
) (*connect.Response[T], error) {
	plan, err := o.ops.Plan(ctx, id)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(wrap(toPlan(plan, who))), nil
}

func toPlan(p Plan, who side) *clustersv1.MeetingPlan {
	return &clustersv1.MeetingPlan{
		Id: p.ID, ClusterId: p.ClusterID, Category: p.Category, Title: p.Title,
		TrainingCourseId: p.TrainingCourseID, TrainingCourse: p.TrainingCourse,
		PlannedOn: p.PlannedOn.Format(isoDate), StartsAt: p.StartsAt, Venue: p.Venue, IsOnline: p.IsOnline,
		Objectives: p.Objectives, Agenda: p.Agenda, ExpectedParticipants: p.ExpectedParticipants,
		Facilitator: p.Facilitator, Resources: p.Resources, Notes: p.Notes, Status: p.Status,
		ActivityId: p.ActivityID, ReviewNote: p.ReviewNote, History: toEvents(p.History),
		// Planned means editable; an edit after approval goes back to staff.
		CanEdit:   who.isLeader && slices.Contains(livePlanStatuses, p.Status),
		CanReview: !who.isLeader && p.Status == "submitted",
		CanCancel: who.isLeader && slices.Contains(livePlanStatuses, p.Status), InvitedCount: p.InvitedCount,
	}
}
