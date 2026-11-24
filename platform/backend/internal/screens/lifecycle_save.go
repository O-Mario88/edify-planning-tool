package screens

import (
	"context"
	"errors"
	"log/slog"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// startActivityPath is my_plan_views.start_activity_action's route.
var startActivityPath = regexp.MustCompile(`^/activities/([A-Za-z0-9]{1,30})/start/action/?$`)

// ActivityStarter is the Go save behind Start activity (internal/activities.Service).
type ActivityStarter interface {
	StartActivity(ctx context.Context, p auth.Principal, activityID, notes string, origin activities.Origin) (activities.Answer, error)
}

// WithActivityLifecycle makes an activity's lifecycle buttons Go's where Go
// takes them. While Django is present its own views keep them.
func (s *Service) WithActivityLifecycle(starter ActivityStarter) *Service {
	s.starter = starter
	return s
}

// lifecycleInGo makes the save in Go; served is false when it is forwarded.
func (s *Service) lifecycleInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.starter == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	m := startActivityPath.FindStringSubmatch(path)
	if m == nil {
		return nil, false, nil
	}
	saved, err := s.starter.StartActivity(ctx, principal, m[1], message.GetValues()["notes"], from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go start failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(saved.Message)}, true, nil
}
