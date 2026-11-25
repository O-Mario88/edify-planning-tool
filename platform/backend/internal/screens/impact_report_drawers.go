package screens

// Impact Assessment's impact report drawers and saves
// (apps.frontend.views.impact_report_views), drawn and saved in Go through
// internal/iareports with Django absent.

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iareports"
)

// ImpactReports is internal/iareports.Reports.
type ImpactReports interface {
	Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error)
	Save(ctx context.Context, p auth.Principal, rawPath string, values map[string]string) (iareports.Saved, bool, error)
}

// WithImpactReports makes the impact report drawers Go's.
func (s *Service) WithImpactReports(r ImpactReports) *Service {
	s.impactReports = r
	return s
}

func (s *Service) impactReportDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.impactReports == nil || s.existingApp != nil || p.InActingAppointment {
		return nil, false, nil
	}
	d, served, err := s.impactReports.Drawer(ctx, p, rawPath)
	if !served {
		return nil, false, nil
	}
	var refused *iareports.Refusal
	switch {
	case errors.As(err, &refused) && refused.Page:
		return &screensv1.GetDrawerResponse{Refusal: refused.Message}, true, nil
	case errors.As(err, &refused) && refused.NotFound:
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, refused.Message)
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) impactReportSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.impactReports == nil || s.existingApp != nil || p.InActingAppointment {
		return nil, false, nil
	}
	saved, served, err := s.impactReports.Save(ctx, p, message.GetPath(), message.GetValues())
	if !served {
		return nil, false, nil
	}
	var refused *iareports.Refusal
	switch {
	case errors.As(err, &refused) && refused.NotFound:
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, refused.Message)
	case errors.As(err, &refused):
		return &screensv1.SaveDrawerResponse{Error: refused.Message}, true, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: saved.Message}, true, nil
}
