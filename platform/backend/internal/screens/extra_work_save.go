package screens

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/extrawork"
)

// ExtraWorker is Extra Assigned Work's saves (internal/extrawork.Service).
type ExtraWorker interface {
	Assign(ctx context.Context, p auth.Principal, v map[string]string, origin activities.Origin) error
	Act(ctx context.Context, p auth.Principal, id, action string, v map[string]string, origin activities.Origin) error
	ActionDrawer(ctx context.Context, p auth.Principal, id, action string) (*screensv1.PageDrawer, error)
}

// WithExtraWork makes Extra Assigned Work's saves Go's, with Django absent.
func (s *Service) WithExtraWork(w ExtraWorker) *Service {
	s.extraWork = w
	return s
}

// extraWorkDrawerInGo is a row button's drawer.
func (s *Service) extraWorkDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	m := extrawork.ActionPath.FindStringSubmatch(path)
	if m == nil || s.extraWork == nil {
		return nil, false, nil
	}
	drawer, err := s.extraWork.ActionDrawer(ctx, p, m[1], m[2])
	var refusal *extrawork.Refusal
	switch {
	case errors.As(err, &refusal):
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, refusal.Message)
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: drawer}, true, nil
}

// extraWorkInGo saves the assign drawer or a row's button.
func (s *Service) extraWorkInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.extraWork == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	path = strings.TrimSuffix(path, "/")
	var err error
	switch m := extrawork.ActionPath.FindStringSubmatch(path); {
	case path == extrawork.AssignPath:
		err = s.extraWork.Assign(ctx, principal, message.GetValues(), from)
	case m != nil:
		err = s.extraWork.Act(ctx, principal, m[1], m[2], message.GetValues(), from)
	default:
		return nil, false, nil
	}
	var refusal *extrawork.Refusal
	switch {
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go extra work save failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: extrawork.SavedMessage}, true, nil
}
