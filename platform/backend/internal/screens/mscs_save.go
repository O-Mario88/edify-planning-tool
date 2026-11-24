package screens

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mscs"
)

// My Targets' Submit MSCS dialog (the page form /my-targets/mscs), saved in
// Go with Django absent.

// StorySubmitter saves a Most Significant Change Story (internal/mscs.Service).
type StorySubmitter interface {
	Submit(ctx context.Context, p auth.Principal, values map[string]string) (string, string, error)
}

// WithStories makes the MSCS dialog's save Go's with Django absent.
func (s *Service) WithStories(st StorySubmitter) *Service {
	s.stories = st
	return s
}

func (s *Service) mscsInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	path, _, _ := strings.Cut(message.GetPath(), "?")
	if !ok || s.stories == nil || s.existingApp != nil || message.GetForm() != mscs.FormKey || strings.TrimSuffix(path, "/") != "/my-targets" {
		return nil, false, nil
	}
	said, refusal, err := s.stories.Submit(ctx, p, message.GetValues())
	switch {
	case errors.Is(err, mscs.ErrHandOn):
		return nil, false, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go MSCS save failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	case refusal != "":
		return &screensv1.SaveDrawerResponse{Saved: false, Error: refusal}, true, nil
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: said}, true, nil
}
