package settingspage

import (
	"context"
	"errors"
	"log/slog"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Handler serves SettingsScreenService for the signed-in caller.
type Handler struct {
	service *Service
	logger  *slog.Logger
}

// NewHandler returns the service's Connect handler.
func NewHandler(service *Service, logger *slog.Logger) *Handler {
	return &Handler{service: service, logger: logger}
}

// GetSettings answers the caller's own Settings page; a role the page
// refuses is permission denied (the existing Access Denied), and an acting
// appointment is handed on to the existing page.
func (h *Handler) GetSettings(
	ctx context.Context, _ *connect.Request[screensv1.GetSettingsRequest],
) (*connect.Response[screensv1.GetSettingsResponse], error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	response, err := h.service.Build(ctx, principal)
	switch {
	case errors.Is(err, ErrNotAvailable):
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not have permission to view Settings.")
	case errors.Is(err, ErrActing):
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonActingNotSupported,
			"Settings in an acting appointment opens in the existing web app.")
	case err != nil:
		return nil, apierr.Internal(ctx, h.logger, err)
	}
	return connect.NewResponse(response), nil
}
