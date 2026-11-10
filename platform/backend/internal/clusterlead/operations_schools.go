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

// Mobilisation (brief A5) and meeting execution (A6). An invitation and its
// answer are one record; attendance is another. A school is "attended" or
// "absent" only from an attendance record: the official one staff keep on
// the activity once they complete it, else the leader's own — never from
// what the school answered.

var channels = map[string]bool{"in_person": true, "phone": true, "sms": true, "email": true, "whatsapp": true}
var answers = map[string]bool{"acknowledged": true, "confirmed": true, "declined": true}

// stateOf is a school's mobilisation state and where an attendance state
// came from ("official", "leader" or "").
func stateOf(invitation *Invitation, leader *AttendanceRecord, officialAttended, isHeld, hasPassed bool) (string, string) {
	switch {
	case officialAttended:
		return "attended", "official"
	case isHeld && invitation != nil:
		// Staff completed it and did not record this invited school.
		return "absent", "official"
	case leader != nil && leader.Attended:
		return "attended", "leader"
	case leader != nil:
		return "absent", "leader"
	case invitation == nil:
		return "not_invited", ""
	case hasPassed && (invitation.Status == "invited" || invitation.Status == "acknowledged"):
		return "no_response", ""
	default:
		return invitation.Status, ""
	}
}

// GetMobilization returns an activity's member schools with each one's state.
func (o *OperationsService) GetMobilization(
	ctx context.Context, request *connect.Request[clustersv1.GetMobilizationRequest],
) (*connect.Response[clustersv1.GetMobilizationResponse], error) {
	activity, _, err := o.activityOf(ctx, request.Msg.GetActivityId())
	if err != nil {
		return nil, err
	}
	members, _, err := o.data.MemberSchools(ctx, activity.ClusterID, "", maxSchoolsOnce, 0)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	invitations, err := o.ops.Invitations(ctx, activity.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	records, err := o.ops.Attendance(ctx, activity.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	minutes, err := o.ops.MinutesOf(ctx, activity.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	byInvite := map[string]*Invitation{}
	for i := range invitations {
		byInvite[invitations[i].SchoolID] = &invitations[i]
	}
	byRecord := map[string]*AttendanceRecord{}
	for i := range records {
		byRecord[records[i].SchoolID] = &records[i]
	}
	isHeld := slices.Contains(deliveredStatuses, activity.Status)
	hasPassed := activity.Date != nil && activity.Date.Before(o.today())
	response := &clustersv1.GetMobilizationResponse{
		Activity:            toActivity(activity.Activity),
		CanInvite:           o.canInvite(activity),
		CanRecordAttendance: activity.Date != nil && !activity.Date.After(o.today()) && activity.Status != "cancelled",
		Minutes:             toMinutes(minutes),
		Counts:              map[string]int32{},
	}
	for _, school := range members {
		row := toSchoolMobilization(school, byInvite[school.ID], byRecord[school.ID],
			slices.Contains(activity.AttendedSchoolIDs, school.ID), isHeld, hasPassed)
		response.Counts[row.GetState()]++
		response.Schools = append(response.Schools, row)
	}
	response.Activity.ConfirmedSchools = response.Counts["confirmed"]
	return connect.NewResponse(response), nil
}

func (o *OperationsService) canInvite(activity ActivityRecord) bool {
	return slices.Contains(plannedStatuses, activity.Status) && activity.Date != nil && !activity.Date.Before(o.today())
}

// InviteSchools invites member schools to a live activity not yet held.
func (o *OperationsService) InviteSchools(
	ctx context.Context, request *connect.Request[clustersv1.InviteSchoolsRequest],
) (*connect.Response[clustersv1.InviteSchoolsResponse], error) {
	activity, who, err := o.activityOf(ctx, request.Msg.GetActivityId())
	if err != nil {
		return nil, err
	}
	if !who.isLeader {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, "Only the cluster's leader mobilises its schools.")
	}
	if !o.canInvite(activity) {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"Schools are invited to a planned activity that has not taken place yet.")
	}
	channel := request.Msg.GetChannel()
	if !channels[channel] {
		return nil, invalid(ctx, "Say how the schools were invited: in person, phone, SMS, email or WhatsApp.")
	}
	wanted := slices.Compact(slices.Sorted(slices.Values(request.Msg.GetSchoolIds())))
	if len(wanted) == 0 || len(wanted) > maxSchoolsOnce {
		return nil, invalid(ctx, "Choose between 1 and 500 schools.")
	}
	members, _, err := o.data.MemberSchools(ctx, activity.ClusterID, "", maxSchoolsOnce, 0)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	for _, id := range wanted {
		if !slices.ContainsFunc(members, func(s School) bool { return s.ID == id }) {
			return nil, invalid(ctx, "Only the cluster's member schools can be invited.")
		}
	}
	ids := make([]string, len(wanted))
	for i := range ids {
		if ids[i], err = newID(); err != nil {
			return nil, o.internal(ctx, err)
		}
	}
	invited, err := o.ops.Invite(ctx, activity.ClusterID, activity.ID, wanted, ids, channel, who.principal.UserID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.InviteSchoolsResponse{
		Invited: int32(invited), AlreadyInvited: int32(len(wanted) - invited), // #nosec G115 -- at most maxSchoolsOnce
	}), nil
}

// RecordResponse records what a school answered its invitation.
func (o *OperationsService) RecordResponse(
	ctx context.Context, request *connect.Request[clustersv1.RecordResponseRequest],
) (*connect.Response[clustersv1.RecordResponseResponse], error) {
	invitation, activity, who, err := o.invitationFor(ctx, request.Msg.GetInvitationId())
	if err != nil {
		return nil, err
	}
	if !answers[request.Msg.GetStatus()] {
		return nil, invalid(ctx, "An answer is acknowledged, confirmed or declined.")
	}
	note, err := textOf(ctx, "The note", request.Msg.GetNote(), maxReasonLength, false)
	if err != nil {
		return nil, err
	}
	if err := o.ops.RespondInvitation(ctx, invitation.ID, request.Msg.GetStatus(), note, who.principal.UserID); err != nil {
		return nil, o.internal(ctx, err)
	}
	row, err := o.schoolRow(ctx, activity, invitation.SchoolID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.RecordResponseResponse{School: row}), nil
}

// FollowUp records one more follow-up of an invitation.
func (o *OperationsService) FollowUp(
	ctx context.Context, request *connect.Request[clustersv1.FollowUpRequest],
) (*connect.Response[clustersv1.FollowUpResponse], error) {
	invitation, activity, who, err := o.invitationFor(ctx, request.Msg.GetInvitationId())
	if err != nil {
		return nil, err
	}
	note, err := textOf(ctx, "The note", request.Msg.GetNote(), maxReasonLength, false)
	if err != nil {
		return nil, err
	}
	if err := o.ops.FollowUpInvitation(ctx, invitation.ID, note, who.principal.UserID); err != nil {
		return nil, o.internal(ctx, err)
	}
	row, err := o.schoolRow(ctx, activity, invitation.SchoolID)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&clustersv1.FollowUpResponse{School: row}), nil
}

// RecordAttendance writes the leader's attendance for an activity whose day
// has come. It changes no invitation, and staff's official record wins.
func (o *OperationsService) RecordAttendance(
	ctx context.Context, request *connect.Request[clustersv1.RecordAttendanceRequest],
) (*connect.Response[clustersv1.RecordAttendanceResponse], error) {
	activity, who, err := o.activityOf(ctx, request.Msg.GetActivityId())
	if err != nil {
		return nil, err
	}
	if !who.isLeader {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, "Only the cluster's leader records its attendance here.")
	}
	if activity.Date == nil || activity.Date.After(o.today()) || activity.Status == "cancelled" {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"Attendance is recorded on or after the activity's day.")
	}
	entries := request.Msg.GetEntries()
	if len(entries) == 0 || len(entries) > maxSchoolsOnce {
		return nil, invalid(ctx, "Record attendance for 1 to 500 schools.")
	}
	members, _, err := o.data.MemberSchools(ctx, activity.ClusterID, "", maxSchoolsOnce, 0)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	records := make([]AttendanceRecord, 0, len(entries))
	ids := make([]string, 0, len(entries))
	for _, entry := range entries {
		if !slices.ContainsFunc(members, func(s School) bool { return s.ID == entry.GetSchoolId() }) {
			return nil, invalid(ctx, "Attendance is recorded for the cluster's member schools.")
		}
		if entry.GetParticipants() < 0 || entry.GetParticipants() > maxParticipants {
			return nil, invalid(ctx, "Participants must be between 0 and 10000.")
		}
		id, err := newID()
		if err != nil {
			return nil, o.internal(ctx, err)
		}
		ids = append(ids, id)
		records = append(records, AttendanceRecord{SchoolID: entry.GetSchoolId(), Attended: entry.GetAttended(), Participants: entry.GetParticipants()})
	}
	if err := o.ops.RecordAttendance(ctx, activity.ClusterID, activity.ID, records, ids, who.principal.UserID); err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.RecordAttendanceResponse{Recorded: int32(len(records))}), nil // #nosec G115 -- at most maxSchoolsOnce
}

// SaveMinutes writes the meeting's minutes; once submitted they are kept.
func (o *OperationsService) SaveMinutes(
	ctx context.Context, request *connect.Request[clustersv1.SaveMinutesRequest],
) (*connect.Response[clustersv1.SaveMinutesResponse], error) {
	activity, who, err := o.activityOf(ctx, request.Msg.GetActivityId())
	if err != nil {
		return nil, err
	}
	if !who.isLeader {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, "Only the cluster's leader writes its minutes.")
	}
	discussion, err := textOf(ctx, "The discussion", request.Msg.GetDiscussion(), maxTextLength, request.Msg.GetSubmit())
	if err != nil {
		return nil, err
	}
	decisions, err := textOf(ctx, "The decisions", request.Msg.GetDecisions(), maxTextLength, false)
	if err != nil {
		return nil, err
	}
	id, err := newID()
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	err = o.ops.SaveMinutes(ctx, id, activity.ClusterID, activity.ID, discussion, decisions, request.Msg.GetSubmit(), who.principal.UserID)
	if errors.Is(err, ErrNotLive) {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, "These minutes were submitted and are kept as they are.")
	}
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	minutes, err := o.ops.MinutesOf(ctx, activity.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.SaveMinutesResponse{Minutes: toMinutes(minutes)}), nil
}

// invitationFor is an invitation, its activity and the caller, who must be
// the cluster's leader.
func (o *OperationsService) invitationFor(ctx context.Context, id string) (Invitation, ActivityRecord, side, error) {
	if err := validID(ctx, "invitation", id); err != nil {
		return Invitation{}, ActivityRecord{}, side{}, err
	}
	if _, err := principalOf(ctx); err != nil {
		return Invitation{}, ActivityRecord{}, side{}, err
	}
	invitation, err := o.ops.Invitation(ctx, id)
	if errors.Is(err, ErrNotFound) {
		return Invitation{}, ActivityRecord{}, side{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such invitation.")
	}
	if err != nil {
		return Invitation{}, ActivityRecord{}, side{}, o.internal(ctx, err)
	}
	activity, who, err := o.activityOf(ctx, invitation.ActivityID)
	if err == nil && !who.isLeader {
		err = apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, "Only the cluster's leader records answers.")
	}
	return invitation, activity, who, err
}

func (o *OperationsService) schoolRow(ctx context.Context, activity ActivityRecord, schoolID string) (*clustersv1.SchoolMobilization, error) {
	members, _, err := o.data.MemberSchools(ctx, activity.ClusterID, "", maxSchoolsOnce, 0)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	invitations, err := o.ops.Invitations(ctx, activity.ID)
	if err != nil {
		return nil, o.internal(ctx, err)
	}
	for _, school := range members {
		if school.ID != schoolID {
			continue
		}
		var invitation *Invitation
		for i := range invitations {
			if invitations[i].SchoolID == schoolID {
				invitation = &invitations[i]
			}
		}
		return toSchoolMobilization(school, invitation, nil, slices.Contains(activity.AttendedSchoolIDs, schoolID),
			slices.Contains(deliveredStatuses, activity.Status), activity.Date != nil && activity.Date.Before(o.today())), nil
	}
	return &clustersv1.SchoolMobilization{SchoolId: schoolID}, nil
}

func toSchoolMobilization(school School, invitation *Invitation, record *AttendanceRecord, official, isHeld, hasPassed bool) *clustersv1.SchoolMobilization {
	state, source := stateOf(invitation, record, official, isHeld, hasPassed)
	row := &clustersv1.SchoolMobilization{
		SchoolId: school.ID, EdifySchoolId: school.SchoolID, Name: school.Name, District: school.District,
		State: state, AttendanceSource: source,
	}
	if invitation != nil {
		row.InvitationId, row.Channel, row.DeliveryStatus = invitation.ID, invitation.Channel, invitation.DeliveryStatus
		row.FollowUps, row.ResponseNote = invitation.FollowUps, invitation.ResponseNote
		row.InvitedAt, row.RespondedAt = invitation.InvitedAt.UTC().Format(time.RFC3339), isoOrNil(invitation.RespondedAt)
	}
	if record != nil {
		row.Participants = record.Participants
	}
	return row
}

func toMinutes(m *MinutesRecord) *clustersv1.Minutes {
	if m == nil {
		return &clustersv1.Minutes{}
	}
	return &clustersv1.Minutes{Discussion: m.Discussion, Decisions: m.Decisions, Status: m.Status, SubmittedAt: isoOrNil(m.SubmittedAt)}
}
