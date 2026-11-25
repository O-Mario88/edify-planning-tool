package screens

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The Work Plan's Add Non-School Activity save (/work-plan/add, posting to
// /work-plan/add/action) in Go with Django absent.

const workPlanAddPath = "/work-plan/add"

// ProgrammeAdder is the Go Add (internal/activities.Service).
type ProgrammeAdder interface {
	AddProgrammeActivity(ctx context.Context, p auth.Principal, form url.Values, origin activities.Origin) (activities.Answer, error)
}

// WithProgrammeAdd makes the Work Plan's Add Go's with Django absent.
func (s *Service) WithProgrammeAdd(a ProgrammeAdder) *Service {
	s.programmeAdds = a
	return s
}

func (s *Service) workPlanAddSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	if s.programmeAdds == nil || s.existingApp != nil ||
		strings.TrimSuffix(strings.SplitN(message.GetPath(), "?", 2)[0], "/") != workPlanAddPath {
		return nil, false, nil
	}
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, false, nil
	}
	form := make(url.Values, len(message.GetValues()))
	for k, v := range message.GetValues() {
		form.Set(k, v)
	}
	added, err := s.programmeAdds.AddProgrammeActivity(ctx, p, form, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		if s.logger != nil {
			s.logger.InfoContext(ctx, "the Work Plan add is the existing application's", slog.String("why", err.Error()))
		}
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go Work Plan add failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: added.Message}, true, nil
}
