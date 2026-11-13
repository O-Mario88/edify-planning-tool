package screens

import (
	"context"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Navigation builds the reader's bar and menu in Go (internal/navigation).
// served is false for a reader the existing application still answers.
type Navigation interface {
	Build(ctx context.Context, p auth.Principal) (*screensv1.GetNavigationResponse, bool, error)
}

// WithNavigation answers the navigation in Go for anyone working in their
// own role; someone in an acting appointment is still answered by the
// existing application, which withholds the pages the appointment leaves
// with the substantive leader.
func (s *Service) WithNavigation(navigation Navigation) *Service {
	s.navigation = navigation
	return s
}

// GetNavigation returns the caller's bottom bar and menu.
func (s *Service) GetNavigation(
	ctx context.Context, _ *connect.Request[screensv1.GetNavigationRequest],
) (*connect.Response[screensv1.GetNavigationResponse], error) {
	if principal, ok := auth.PrincipalFrom(ctx); ok && s.navigation != nil && !principal.InActingAppointment {
		response, served, err := s.navigation.Build(ctx, principal)
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		if served {
			return connect.NewResponse(response), nil
		}
	}
	return fetch[screensv1.GetNavigationResponse](ctx, s, pathNavigation)
}
