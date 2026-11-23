package screens

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/presence"
)

// PresenceStamper writes the person's presence beat (docs/migration/65).
type PresenceStamper interface {
	Stamp(ctx context.Context, userID string, r presence.Request) (int, error)
}

// WithPresence stamps a person's save when no existing application is there
// to do it. With Django present, the form-only post (or the forwarded save)
// passes through its middleware, so Go adds no second stamp.
func (s *Service) WithPresence(stamper PresenceStamper, logger *slog.Logger) *Service {
	s.presence = stamper
	if logger != nil {
		s.logger = logger
	}
	return s
}

// stampSave makes the beat for a drawer save, whatever its outcome. A failed
// stamp is logged and never changes the answer, as touch_presence swallows
// database errors.
func (s *Service) stampSave(ctx context.Context, path string) {
	if s.presence == nil || s.existingApp != nil {
		return
	}
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return
	}
	_, err := s.presence.Stamp(ctx, principal.UserID, presence.Request{
		Method: http.MethodPost, Path: path, Bearer: true,
	})
	if err != nil && s.logger != nil {
		s.logger.ErrorContext(ctx, "the presence stamp failed", slog.String("error", err.Error()))
	}
}
