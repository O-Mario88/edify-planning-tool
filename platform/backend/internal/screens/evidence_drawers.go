package screens

// Impact Assessment's School Evidence drawers and saves
// (apps.frontend.views.ia_school_evidence_views), drawn and saved in Go
// through internal/schoolevidence with Django absent.

import (
	"context"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolevidence"
)

// EvidenceDrawers is internal/schoolevidence.Evidence.
type EvidenceDrawers interface {
	Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error)
	Save(ctx context.Context, p auth.Principal, rawPath string, values map[string]string) (*schoolevidence.Saved, bool, error)
}

// WithEvidenceDrawers makes School Evidence's drawers Go's.
func (s *Service) WithEvidenceDrawers(e EvidenceDrawers) *Service {
	s.evidence = e
	return s
}

func (s *Service) evidenceDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.evidence == nil || s.existingApp != nil {
		return nil, false, nil
	}
	d, served, err := s.evidence.Drawer(ctx, p, rawPath)
	if !served {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) evidenceSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.evidence == nil || s.existingApp != nil || message.GetForm() != "" {
		return nil, false, nil
	}
	saved, served, err := s.evidence.Save(ctx, p, message.GetPath(), message.GetValues())
	if !served {
		return nil, false, nil
	}
	if err != nil {
		if words, notFound, ok := schoolevidence.IsRefusal(err); ok {
			if notFound {
				return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, words)
			}
			return &screensv1.SaveDrawerResponse{Error: words}, true, nil
		}
		return nil, true, err
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: saved.Message, Redirect: saved.Back}, true, nil
}
