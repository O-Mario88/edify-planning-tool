package screens

import (
	"context"
	"errors"
	"log/slog"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// visitDecisionPath is visit_request_views.visit_request_decide's route.
var visitDecisionPath = regexp.MustCompile(`^/planning/visit-requests/([A-Za-z0-9]{1,30})/(approve|decline)/?$`)

// VisitDecider is the Go save of a school owner's decision on a visit
// request (internal/activities.Service).
type VisitDecider interface {
	DecideVisitRequest(ctx context.Context, p auth.Principal, d activities.VisitDecision, origin activities.Origin) (activities.Answer, error)
}

// WithVisitDecisions makes the owner's decision Go's where Go takes it. While
// Django is present its own view keeps it: the queue page posts straight to
// it, with no form-only door.
func (s *Service) WithVisitDecisions(decider VisitDecider) *Service {
	s.visitDecisions = decider
	return s
}

// visitDecisionInGo makes the decision in Go; served is false when it is forwarded.
func (s *Service) visitDecisionInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.visitDecisions == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	m := visitDecisionPath.FindStringSubmatch(path)
	if m == nil {
		return nil, false, nil
	}
	values := message.GetValues()
	note := values["note"]
	if strings.TrimSpace(note) == "" {
		note = values["reason"]
	}
	saved, err := s.visitDecisions.DecideVisitRequest(ctx, principal, activities.VisitDecision{
		ActivityID: m[1], Decision: m[2], Note: note,
	}, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go visit decision failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(saved.Message)}, true, nil
}
