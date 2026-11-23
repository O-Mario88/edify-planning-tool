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

const coreVisitDrawerPath = "/core-schools/schedule-visit"

// CoreVisitSaver is the Go save of the Core Schools visit form
// (internal/activities.Service).
type CoreVisitSaver interface {
	ScheduleCoreVisit(ctx context.Context, p auth.Principal, req activities.CoreVisitRequest, origin activities.Origin) (activities.Answer, error)
}

// WithCoreVisitSave makes the Core visit form's saves Go's where Go takes
// them. While Django is present its own form keeps them: this form has no
// form-only door to compose the post through.
func (s *Service) WithCoreVisitSave(saver CoreVisitSaver, logger *slog.Logger) *Service {
	s.coreVisits = saver
	if logger != nil {
		s.logger = logger
	}
	return s
}

// coreVisitInGo makes the save in Go; served is false when it is forwarded.
func (s *Service) coreVisitInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.coreVisits == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, rawQuery, _ := strings.Cut(message.GetPath(), "?")
	if path != coreVisitDrawerPath {
		return nil, false, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, false, nil
	}
	req, taken := activities.CoreVisitRequestFromForm(query.Get("school_id"), directDrawerForm(message))
	if !taken {
		return nil, false, nil
	}
	saved, err := s.coreVisits.ScheduleCoreVisit(ctx, principal, req, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go Core visit save failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	words := collapse(saved.Message)
	if notice := collapse(saved.Notice); notice != "" {
		words += " " + notice
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: words}, true, nil
}
