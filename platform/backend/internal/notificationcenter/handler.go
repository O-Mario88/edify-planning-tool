package notificationcenter

import (
	"context"
	"errors"
	"log/slog"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Handler serves NotificationCenterService for the signed-in caller.
type Handler struct {
	service *Service
	logger  *slog.Logger
}

// NewHandler returns the service's Connect handler.
func NewHandler(service *Service, logger *slog.Logger) *Handler {
	return &Handler{service: service, logger: logger}
}

// GetNotificationCenter answers the caller's own notification centre; a
// role the page refuses is permission denied (the existing Access Denied).
func (h *Handler) GetNotificationCenter(
	ctx context.Context, request *connect.Request[screensv1.GetNotificationCenterRequest],
) (*connect.Response[screensv1.GetNotificationCenterResponse], error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	response, err := h.service.Build(ctx, principal, request.Msg)
	if errors.Is(err, ErrNotAvailable) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not have permission to view Dashboard.")
	}
	if errors.Is(err, ErrBodiesWithheld) {
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"The notification centre is not served here yet.")
	}
	if err != nil {
		return nil, apierr.Internal(ctx, h.logger, err)
	}
	return connect.NewResponse(response), nil
}
