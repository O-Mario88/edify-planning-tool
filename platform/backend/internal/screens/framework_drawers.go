package screens

// Impact Assessment's Measurement Framework drawers and saves
// (apps.frontend.views.ia_framework_views), drawn and saved in Go through
// internal/iaframework with Django absent.

import (
	"context"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaframework"
)

// FrameworkDrawers is internal/iaframework.Framework.
type FrameworkDrawers interface {
	Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error)
	Save(ctx context.Context, p auth.Principal, rawPath, form string, values map[string]string) (*iaframework.Saved, bool, error)
}

// WithFrameworkDrawers makes the Measurement Framework's drawers Go's.
func (s *Service) WithFrameworkDrawers(f FrameworkDrawers) *Service {
	s.framework = f
	return s
}

func (s *Service) frameworkDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.framework == nil || s.existingApp != nil {
		return nil, false, nil
	}
	d, served, err := s.framework.Drawer(ctx, p, rawPath)
	if !served {
		return nil, false, nil
	}
	if err != nil {
		if message, notFound, ok := iaframework.IsRefusal(err); ok && notFound {
			return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, message)
		}
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) frameworkSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.framework == nil || s.existingApp != nil {
		return nil, false, nil
	}
	saved, served, err := s.framework.Save(ctx, p, message.GetPath(), message.GetForm(), message.GetValues())
	if !served {
		return nil, false, nil
	}
	if err != nil {
		if words, notFound, ok := iaframework.IsRefusal(err); ok {
			if notFound {
				return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, words)
			}
			return &screensv1.SaveDrawerResponse{Error: words}, true, nil
		}
		return nil, true, err
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: saved.Message, Redirect: saved.Back}, true, nil
}
