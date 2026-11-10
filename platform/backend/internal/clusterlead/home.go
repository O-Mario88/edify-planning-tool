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

	response := &clustersv1.GetClusterHomeResponse{
		Cluster: summary,
		Overview: []*clustersv1.HomeCount{
			{Key: "member_schools", Label: "Member schools", Value: summary.GetMemberSchoolCount(), Href: "schools"},
			{Key: "upcoming_meetings", Label: "Upcoming activities", Value: int32(len(upcoming)), Href: "activities?when=upcoming"}, // #nosec G115 -- at most upcomingLimit
		},
		QuickActions: quickActions(),
	}
	for _, activity := range upcoming {
		response.Upcoming = append(response.Upcoming, toActivity(activity))
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

// quickActions are the Home's shortcuts. One that is not built yet says so
// rather than leading nowhere.
func quickActions() []*clustersv1.QuickAction {
	const planning = "Meeting planning and mobilisation arrive with cluster operations."
	return []*clustersv1.QuickAction{
		{Key: "plan_meeting", Label: "Plan Meeting", Reason: planning},
		{Key: "mobilize", Label: "Mobilize Schools", Reason: planning},
		{Key: "schools", Label: "View Member Schools", Enabled: true, Href: "schools"},
		{Key: "attendance", Label: "Record Attendance", Reason: planning},
		{Key: "performance", Label: "View Cluster Performance",
			Reason: "Cluster performance arrives with the Impact Intelligence Engine."},
	}
}
