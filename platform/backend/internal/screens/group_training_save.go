package screens

import (
	"context"
	"log/slog"
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// A cluster's Group Training through Go (docs/migration/38), behind
// EDIFY_GO_SAVES=schedule_group_training, off by default. Nothing calls it
// yet: the app's drawer feed does not open the cluster drawer (38.1), and
// making it native is not behaviour-neutral (38.5 §5). It is here so the app
// or the web can hand the drawer's posted form to Go later and answer in
// the existing feed's words, as the visit save does.

// GroupTrainingSaver is the Go Group Training save (internal/activities.Service).
type GroupTrainingSaver interface {
	ScheduleGroupTraining(ctx context.Context, p auth.Principal, req activities.GroupTrainingRequest,
		origin activities.Origin) (activities.Answer, error)
}

// WithGroupTrainingSave makes a cluster's Group Training saves Go's where
// Go takes them.
func (s *Service) WithGroupTrainingSave(saver GroupTrainingSaver, logger *slog.Logger) *Service {
	s.groupTrainings, s.logger = saver, logger
	return s
}

// ScheduleGroupTrainingInGo makes the drawer's posted form's save in Go;
// served is false when the form is to be forwarded to the existing
// application as before (the switch off, a case Go does not take, or a
// hand-on), so a save is never made by both.
func (s *Service) ScheduleGroupTrainingInGo(ctx context.Context, form url.Values, origin activities.Origin) (
	*screensv1.SavePlanningDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.groupTrainings == nil || principal.InActingAppointment {
		return nil, false, nil
	}
	req, taken := activities.GroupTrainingRequestFromForm(form)
	if !taken {
		return nil, false, nil
	}
	saved, err := s.groupTrainings.ScheduleGroupTraining(ctx, principal, req, origin)
	return outcomeOf(ctx, s.logger, saved, err)
}
