package clusterlead

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// Action items (brief A6), requests to staff (A2) and the cluster report (A7).

// ListActionItems returns the cluster's action items.
func (o *OperationsService) ListActionItems(
	ctx context.Context, request *connect.Request[clustersv1.ListActionItemsRequest],
) (*connect.Response[clustersv1.ListActionItemsResponse], error) {
	if _, err := o.access(ctx, request.Msg.GetClusterId()); err != nil {
		return nil, err
	}
	items, err := o.ops.Items(ctx, request.Msg.GetClusterId(), request.Msg.GetOpenOnly())
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	response := &clustersv1.ListActionItemsResponse{}
	for _, item := range items {
		response.Items = append(response.Items, o.toItem(item))
	}
	return connect.NewResponse(response), nil
}

// SaveActionItem creates or edits an open action item. Its owner is a
// member school or a named person.
func (o *OperationsService) SaveActionItem(
	ctx context.Context, request *connect.Request[clustersv1.SaveActionItemRequest],
) (*connect.Response[clustersv1.SaveActionItemResponse], error) {
	msg := request.Msg
	who, err := o.access(ctx, msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	title, err := textOf(ctx, "A title", msg.GetTitle(), maxTitleLength, true)
	if err != nil {
		return nil, err
	}
	ownerName, err := textOf(ctx, "The owner", msg.GetOwnerName(), maxTitleLength, false)
	if err != nil {
		return nil, err
	}
	if msg.GetOwnerSchoolId() == "" && ownerName == "" {
		return nil, invalid(ctx, "Name who owns it: a member school or a person.")
	}
	if msg.GetOwnerSchoolId() != "" {
		members, _, err := o.data.MemberSchools(ctx, msg.GetClusterId(), "", maxSchoolsOnce, 0)
		if err != nil {
			return nil, o.internal(ctx, err)
		}
		if !slices.ContainsFunc(members, func(s School) bool { return s.ID == msg.GetOwnerSchoolId() }) {
			return nil, invalid(ctx, "An owner school is one of the cluster's member schools.")
		}
	}
	var due *time.Time
	if msg.GetDueOn() != "" {
		parsed, err := time.Parse(isoDate, msg.GetDueOn())
		if err != nil {
			return nil, invalid(ctx, "The due date must be a date (YYYY-MM-DD).")
		}
		due = &parsed
	}
	if msg.GetActivityId() != "" {
		activity, err := o.ops.ActivityFor(ctx, msg.GetActivityId())
		if err != nil || activity.ClusterID != msg.GetClusterId() {
			return nil, invalid(ctx, "The meeting must be one of this cluster's.")
		}
	}
	item := Item{ID: msg.GetId(), ClusterID: msg.GetClusterId(), ActivityID: msg.GetActivityId(), Title: title,
		OwnerSchoolID: msg.GetOwnerSchoolId(), DueOn: due}
	isNew := item.ID == ""
	if isNew {
		if item.ID, err = newID(); err != nil {
			return nil, o.internal(ctx, err)
		}
	} else if existing, err := o.ops.ItemByID(ctx, item.ID); err != nil || existing.ClusterID != item.ClusterID {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such action item in this cluster.")
	}
	if err := o.ops.SaveItem(ctx, item, ownerName, isNew, who.principal.UserID); err != nil {
		if errors.Is(err, ErrNotLive) {
			return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "A closed action item is kept as it is.")
		}
		return nil, o.internal(ctx, err)
	}
	saved, err := o.ops.ItemByID(ctx, item.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.SaveActionItemResponse{Item: o.toItem(saved)}), nil
}

// CloseActionItem marks an item done or cancelled.
func (o *OperationsService) CloseActionItem(
	ctx context.Context, request *connect.Request[clustersv1.CloseActionItemRequest],
) (*connect.Response[clustersv1.CloseActionItemResponse], error) {
	if err := validID(ctx, "action item", request.Msg.GetId()); err != nil {
		return nil, err
	}
	if _, err := principalOf(ctx); err != nil {
		return nil, err
	}
	item, err := o.ops.ItemByID(ctx, request.Msg.GetId())
	if errors.Is(err, ErrNotFound) {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such action item.")
	}
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	who, err := o.access(ctx, item.ClusterID)
	if err != nil {
		return nil, err
	}
	status := request.Msg.GetStatus()
	if status != "done" && status != "cancelled" {
		return nil, invalid(ctx, "An action item closes as done or cancelled.")
	}
	note, err := textOf(ctx, "The note", request.Msg.GetNote(), maxReasonLength, false)
	if err != nil {
		return nil, err
	}
	if err := o.ops.CloseItem(ctx, item.ID, status, note, who.principal.UserID); err != nil {
		if errors.Is(err, ErrNotLive) {
			return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "This action item is already closed.")
		}
		return nil, o.internal(ctx, err)
	}
	closed, err := o.ops.ItemByID(ctx, item.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.CloseActionItemResponse{Item: o.toItem(closed)}), nil
}

func (o *OperationsService) toItem(i Item) *clustersv1.ActionItem {
	out := &clustersv1.ActionItem{
		Id: i.ID, ClusterId: i.ClusterID, ActivityId: i.ActivityID, Title: i.Title,
		OwnerSchoolId: i.OwnerSchoolID, Owner: i.Owner, Status: i.Status, History: toEvents(i.History),
	}
	if i.DueOn != nil {
		out.DueOn = i.DueOn.Format(isoDate)
		out.IsOverdue = i.Status == "open" && i.DueOn.Before(o.today())
	}
	return out
}

// ListRequests returns the cluster's requests to staff.
func (o *OperationsService) ListRequests(
	ctx context.Context, request *connect.Request[clustersv1.ListRequestsRequest],
) (*connect.Response[clustersv1.ListRequestsResponse], error) {
	if _, err := o.access(ctx, request.Msg.GetClusterId()); err != nil {
		return nil, err
	}
	requests, err := o.ops.Requests(ctx, request.Msg.GetClusterId())
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	response := &clustersv1.ListRequestsResponse{}
	for _, r := range requests {
		response.Requests = append(response.Requests, toRequest(r))
	}
	return connect.NewResponse(response), nil
}

// SubmitRequest records the leader's request or concern to staff.
func (o *OperationsService) SubmitRequest(
	ctx context.Context, request *connect.Request[clustersv1.SubmitRequestRequest],
) (*connect.Response[clustersv1.SubmitRequestResponse], error) {
	who, err := o.leaderOf(ctx, request.Msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	subject, err := textOf(ctx, "A subject", request.Msg.GetSubject(), maxTitleLength, true)
	if err != nil {
		return nil, err
	}
	body, err := textOf(ctx, "What you need", request.Msg.GetBody(), maxTextLength, true)
	if err != nil {
		return nil, err
	}
	id, err := newID()
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	if err := o.ops.CreateRequest(ctx, id, request.Msg.GetClusterId(), subject, body, who.principal.UserID); err != nil {
		return nil, o.internal(ctx, err)
	}
	saved, err := o.ops.RequestByID(ctx, id)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.SubmitRequestResponse{Request: toRequest(saved)}), nil
}

// AnswerRequest answers a leader's request (staff only).
func (o *OperationsService) AnswerRequest(
	ctx context.Context, request *connect.Request[clustersv1.AnswerRequestRequest],
) (*connect.Response[clustersv1.AnswerRequestResponse], error) {
	if err := validID(ctx, "request", request.Msg.GetId()); err != nil {
		return nil, err
	}
	if _, err := principalOf(ctx); err != nil {
		return nil, err
	}
	found, err := o.ops.RequestByID(ctx, request.Msg.GetId())
	if errors.Is(err, ErrNotFound) {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such request.")
	}
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	who, err := o.staffOf(ctx, found.ClusterID)
	if err != nil {
		return nil, err
	}
	answer, err := textOf(ctx, "The answer", request.Msg.GetAnswer(), maxTextLength, true)
	if err != nil {
		return nil, err
	}
	if err := o.ops.AnswerRequestRecord(ctx, found.ID, answer, who.principal.UserID); err != nil {
		if errors.Is(err, ErrNotLive) {
			return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "This request is already answered.")
		}
		return nil, o.internal(ctx, err)
	}
	saved, err := o.ops.RequestByID(ctx, found.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.AnswerRequestResponse{Request: toRequest(saved)}), nil
}

func toRequest(r Request) *clustersv1.LeaderRequest {
	return &clustersv1.LeaderRequest{
		Id: r.ID, ClusterId: r.ClusterID, Subject: r.Subject, Body: r.Body, Status: r.Status,
		AskedBy: r.AskedBy, AskedAt: r.AskedAt.UTC().Format(time.RFC3339), Answer: r.Answer,
		AnsweredBy: r.AnsweredBy, AnsweredAt: isoOrNil(r.AnsweredAt),
	}
}

// GetClusterReport counts the cluster's financial year (brief A7).
func (o *OperationsService) GetClusterReport(
	ctx context.Context, request *connect.Request[clustersv1.GetClusterReportRequest],
) (*connect.Response[clustersv1.GetClusterReportResponse], error) {
	if _, err := o.access(ctx, request.Msg.GetClusterId()); err != nil {
		return nil, err
	}
	start, end, year := fiscalYear(o.today())
	data, err := o.ops.Report(ctx, request.Msg.GetClusterId(), start, end)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	rate := "—"
	if data.SchoolsInvited > 0 {
		rate = fmt.Sprintf("%d%%", data.SchoolsParticipating*100/data.SchoolsInvited)
	}
	response := &clustersv1.GetClusterReportResponse{
		Period: fmt.Sprintf("FY %d", year),
		Figures: []*clustersv1.ReportFigure{
			{Key: "meetings_planned", Label: "Meetings planned", Value: fmt.Sprint(data.MeetingsPlanned)},
			{Key: "meetings_held", Label: "Meetings held", Value: fmt.Sprint(data.MeetingsHeld)},
			{Key: "trainings_planned", Label: "Trainings planned", Value: fmt.Sprint(data.TrainingsPlanned)},
			{Key: "trainings_held", Label: "Trainings held", Value: fmt.Sprint(data.TrainingsHeld)},
			{Key: "schools_invited", Label: "Schools invited", Value: fmt.Sprint(data.SchoolsInvited)},
			{Key: "schools_participating", Label: "Schools participating", Value: fmt.Sprint(data.SchoolsParticipating)},
			{Key: "participation_rate", Label: "Participation rate", Value: rate},
			{Key: "open_action_items", Label: "Open action items", Value: fmt.Sprint(data.OpenItems)},
		},
		NeedsStaff: []*clustersv1.ReportCount{
			{Label: "Plans awaiting review", Count: data.PlansToReview},
			{Label: "Requests awaiting an answer", Count: data.OpenRequests},
		},
	}
	for _, a := range data.Absent {
		response.RepeatedlyAbsent = append(response.RepeatedlyAbsent, &clustersv1.ReportSchool{
			SchoolId: a.ID, EdifySchoolId: a.SchoolID, Name: a.Name, Absences: a.Absences, Invitations: a.Invited,
		})
	}
	for _, c := range data.TrainingByIntervention {
		response.TrainingByIntervention = append(response.TrainingByIntervention, &clustersv1.ReportCount{Label: c.Label, Count: c.Count})
	}
	for _, c := range data.SSAStatus {
		response.SsaStatus = append(response.SsaStatus, &clustersv1.ReportCount{Label: c.Label, Count: c.Count})
	}
	return connect.NewResponse(response), nil
}
