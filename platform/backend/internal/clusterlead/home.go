package clusterlead

import (
	"context"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
)

// kindLabels names an existing cluster meeting's kind (apps/core/enums.py
// MeetingKind); a blank kind predates the kinds.
var kindLabels = map[string]string{
	"training":        "Cluster Training",
	"only_meeting":    "Only Meeting",
	"cluster_leaders": "Cluster Leaders Meeting",
	"":                "Cluster Meeting",
}

// GetClusterHome is the leader's Home for one of their clusters (brief A3).
// Every figure is counted from existing or portal records, and each count
// names the list it opens.
func (s *Service) GetClusterHome(
	ctx context.Context, request *connect.Request[clustersv1.GetClusterHomeRequest],
) (*connect.Response[clustersv1.GetClusterHomeResponse], error) {
	principal, err := leader(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.checkReady(ctx); err != nil {
		return nil, err
	}
	clusterID := request.Msg.GetClusterId()
	mine, err := s.liveFor(ctx, principal.UserID, clusterID)
	if err != nil {
		return nil, err
	}
	summary, err := s.summary(ctx, clusterID, &mine)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	upcoming, err := s.data.UpcomingActivities(ctx, clusterID, s.today(), upcomingLimit)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	next := ""
	if len(upcoming) > 0 {
		next = upcoming[0].ID
	}
	ops, err := s.data.OperationsOf(ctx, clusterID, next, s.today())
	if err != nil {
		return nil, s.internal(ctx, err)
	}

	response := &clustersv1.GetClusterHomeResponse{
		Cluster: summary,
		Overview: []*clustersv1.HomeCount{
			{Key: "member_schools", Label: "Member schools", Value: summary.GetMemberSchoolCount(), Href: "schools"},
			{Key: "upcoming_meetings", Label: "Upcoming activities", Value: int32(len(upcoming)), Href: "activities?when=upcoming"}, // #nosec G115 -- at most upcomingLimit
			{Key: "to_mobilise", Label: "Schools to mobilise", Value: ops.NotInvitedToNext, Href: "activities?when=upcoming"},
			{Key: "outstanding_responses", Label: "Outstanding responses", Value: ops.Unanswered, Href: "activities?when=upcoming"},
			{Key: "pending_actions", Label: "Pending actions", Value: ops.OpenItems, Href: "actions"},
		},
		PriorityActions: priorityActions(ops),
		QuickActions:    quickActions(),
	}
	for _, activity := range upcoming {
		row := toActivity(activity)
		row.ConfirmedSchools = ops.Confirmed[activity.ID]
		response.Upcoming = append(response.Upcoming, row)
	}
	return connect.NewResponse(response), nil
}

// priorityActions is what needs the leader, most pressing first; a count of
// nothing is left out.
func priorityActions(ops Operations) []*clustersv1.PriorityAction {
	all := []*clustersv1.PriorityAction{
		{Key: "returned_plans", Label: "Meetings to revise", Count: ops.Returned,
			Detail: "Plans your CCEO returned for changes", Href: "plans", Tone: "alert"},
		{Key: "overdue_items", Label: "Outstanding follow-ups", Count: ops.Overdue,
			Detail: "Action items past their due date", Href: "actions", Tone: "alert"},
		{Key: "unanswered", Label: "Schools yet to respond", Count: ops.Unanswered,
			Detail: "Invited to an upcoming activity, no answer yet", Href: "activities?when=upcoming", Tone: "caution"},
		{Key: "to_mobilise", Label: "Schools not yet invited", Count: ops.NotInvitedToNext,
			Detail: "Member schools not invited to the next activity", Href: "activities?when=upcoming", Tone: "caution"},
		{Key: "trainings_short", Label: "Training with incomplete mobilisation", Count: ops.TrainingsShort,
			Detail: "Upcoming trainings with schools not yet invited", Href: "activities?when=upcoming", Tone: "caution"},
		{Key: "minutes_due", Label: "Minutes awaiting submission", Count: ops.MinutesDue,
			Detail: "Meetings held in the last 60 days", Href: "activities?when=past", Tone: "info"},
	}
	out := make([]*clustersv1.PriorityAction, 0, len(all))
	for _, action := range all {
		if action.GetCount() > 0 {
			out = append(out, action)
		}
	}
	return out
}

// ListActivities returns the cluster's upcoming or past activities.
func (s *Service) ListActivities(
	ctx context.Context, request *connect.Request[clustersv1.ListActivitiesRequest],
) (*connect.Response[clustersv1.ListActivitiesResponse], error) {
	principal, err := leader(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.checkReady(ctx); err != nil {
		return nil, err
	}
	clusterID := request.Msg.GetClusterId()
	if _, err := s.liveFor(ctx, principal.UserID, clusterID); err != nil {
		return nil, err
	}
	var activities []Activity
	if request.Msg.GetWhen() == "past" {
		activities, err = s.data.PastActivities(ctx, clusterID, s.today(), maxPageSize)
	} else {
		activities, err = s.data.UpcomingActivities(ctx, clusterID, s.today(), maxPageSize)
	}
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &clustersv1.ListActivitiesResponse{}
	for _, activity := range activities {
		response.Activities = append(response.Activities, toActivity(activity))
	}
	return connect.NewResponse(response), nil
}

func toActivity(a Activity) *clustersv1.ClusterActivity {
	out := &clustersv1.ClusterActivity{
		Id: a.ID, Name: a.Name, Location: a.Venue, Type: kindLabels[a.Kind],
		InvitedSchools: a.Invited, Status: a.Status,
	}
	if out.Type == "" {
		out.Type = kindLabels[""]
	}
	if out.Name == "" {
		out.Name = out.Type
	}
	if a.Date != nil {
		out.Date = a.Date.Format(isoDate)
	}
	return out
}

// quickActions are the Home's shortcuts (brief A3).
func quickActions() []*clustersv1.QuickAction {
	return []*clustersv1.QuickAction{
		{Key: "plan_meeting", Label: "Plan Meeting", Enabled: true, Href: "plans"},
		{Key: "mobilize", Label: "Mobilize Schools", Enabled: true, Href: "activities?when=upcoming"},
		{Key: "schools", Label: "View Member Schools", Enabled: true, Href: "schools"},
		{Key: "attendance", Label: "Record Attendance", Enabled: true, Href: "activities?when=past"},
		{Key: "performance", Label: "View Cluster Performance", Enabled: true, Href: "report"},
	}
}
