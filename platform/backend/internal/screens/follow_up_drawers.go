package screens

// The Staff Activity follow-ups (apps.frontend.views.staff_activity_views'
// follow-up views) drawn and saved in Go through internal/staffactivity
// with Django absent: Follow up, the Follow-up Queue, one follow-up and its
// steps.

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffactivity"
)

// FollowUpDrawers is internal/staffactivity.FollowUps.
type FollowUpDrawers interface {
	Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error)
	Save(ctx context.Context, p auth.Principal, rawPath, form string, values map[string]string) (*screensv1.SaveDrawerResponse, bool, error)
}

// WithFollowUpDrawers makes the Staff Activity follow-ups Go's.
func (s *Service) WithFollowUpDrawers(f FollowUpDrawers) *Service {
	s.followUps = f
	return s
}

// followUpRefusal is the view's 403 or 404 as the API's answer.
func followUpRefusal(ctx context.Context, err error) error {
	var refused *staffactivity.Refused
	if !errors.As(err, &refused) {
		return err
	}
	if refused.NotFound {
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This was not found, or it is not yours to view.")
	}
	return apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, refused.Message)
}

func (s *Service) followUpDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.followUps == nil || s.existingApp != nil {
		return nil, false, nil
	}
	d, served, err := s.followUps.Drawer(ctx, p, rawPath)
	if !served {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, followUpRefusal(ctx, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) followUpSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.followUps == nil || s.existingApp != nil {
		return nil, false, nil
	}
	answer, served, err := s.followUps.Save(ctx, p, message.GetPath(), message.GetForm(), message.GetValues())
	if !served {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, followUpRefusal(ctx, err)
	}
	return answer, true, nil
}
