package screens

import (
	"context"
	"log/slog"
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// A cluster meeting through Go (docs/migration/49), behind
// EDIFY_GO_SAVES=schedule_cluster_meeting, off by default. Nothing calls it
// yet: the app's drawer feed does not open the cluster drawer (38.1). It is
// here so the app or the web can hand the drawer's posted form to Go later
// and answer in the existing feed's words, as the Group Training does.

// ClusterMeetingSaver is the Go cluster meeting save (internal/activities.Service).
type ClusterMeetingSaver interface {
	ScheduleClusterMeeting(ctx context.Context, p auth.Principal, req activities.ClusterMeetingRequest,
		origin activities.Origin) (activities.Answer, error)
}

// WithClusterMeetingSave makes a cluster's meeting saves Go's where Go
// takes them.
func (s *Service) WithClusterMeetingSave(saver ClusterMeetingSaver, logger *slog.Logger) *Service {
	s.clusterMeetings, s.logger = saver, logger
	return s
}

// ScheduleClusterMeetingInGo makes the drawer's posted form's save in Go;
// served is false when the form is to be forwarded to the existing
// application as before (the switch off, a case Go does not take, or a
// hand-on), so a save is never made by both.
func (s *Service) ScheduleClusterMeetingInGo(ctx context.Context, form url.Values, origin activities.Origin) (
	*screensv1.SavePlanningDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.clusterMeetings == nil || principal.InActingAppointment {
		return nil, false, nil
	}
	req, taken := activities.ClusterMeetingRequestFromForm(form)
	if !taken {
		return nil, false, nil
	}
	saved, err := s.clusterMeetings.ScheduleClusterMeeting(ctx, principal, req, origin)
	return outcomeOf(ctx, s.logger, saved, err)
}
