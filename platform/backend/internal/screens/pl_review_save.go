package screens

import (
	"context"
	"errors"
	"log/slog"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
)

// PLReviewer performs Programme Lead completion approvals and returns natively
// in Go (internal/plreview.ReviewService) with zero Django calls.
type PLReviewer interface {
	Approve(ctx context.Context, p auth.Principal, activityID string) (plreview.ReviewResult, error)
	Return(ctx context.Context, p auth.Principal, activityID, reason string) (plreview.ReviewResult, error)
}

// WithPLReviewSave enables native Go Programme Lead approve/return drawer saves
// (EDIFY_GO_SAVES=pl_review).
func (s *Service) WithPLReviewSave(reviewer PLReviewer, logger *slog.Logger) *Service {
	s.plReviews, s.logger = reviewer, logger
	return s
}

var (
	plConfirmPath = regexp.MustCompile(`^/pl/review-queue/([A-Za-z0-9]{1,30})/confirm/?$`)
	plReturnPath  = regexp.MustCompile(`^/pl/review-queue/([A-Za-z0-9]{1,30})/return/?$`)
	plDrawerPath  = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/pl-review/?$`)
)

// plReviewInGo executes Programme Lead approval or return natively in Go with
// zero ?form_only=1 or Django relay calls.
func (s *Service) plReviewInGo(
	ctx context.Context, message *screensv1.SaveDrawerRequest,
) (*screensv1.SaveDrawerResponse, bool, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.plReviews == nil || principal.InActingAppointment {
		return nil, false, nil
	}
	path := message.GetPath()
	values := message.GetValues()

	var activityID, action string
	switch {
	case plConfirmPath.MatchString(path):
		activityID = plConfirmPath.FindStringSubmatch(path)[1]
		action = "approve"
	case plReturnPath.MatchString(path):
		activityID = plReturnPath.FindStringSubmatch(path)[1]
		action = "return"
	case plDrawerPath.MatchString(path):
		activityID = plDrawerPath.FindStringSubmatch(path)[1]
		decision := strings.ToLower(strings.TrimSpace(values["decision"]))
		if decision == "" {
			decision = strings.ToLower(strings.TrimSpace(values["action"]))
		}
		switch decision {
		case "approve", "confirm", "verify":
			action = "approve"
		case "return", "reject":
			action = "return"
		default:
			return nil, false, nil
		}
	default:
		return nil, false, nil
	}

	var (
		res plreview.ReviewResult
		err error
	)
	if action == "approve" {
		res, err = s.plReviews.Approve(ctx, principal, activityID)
	} else {
		reason := strings.TrimSpace(values["reason"])
		if reason == "" {
			reason = strings.TrimSpace(values["comment"])
		}
		res, err = s.plReviews.Return(ctx, principal, activityID, reason)
	}
	var refusal *plreview.ReviewRefusal
	switch {
	case errors.As(err, &refusal) && refusal.Forbidden:
		return nil, true, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, refusal.Message)
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: refusal.Message}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "plreview: native Go save failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	msg := "Completion approved and verified."
	if res.Status == "returned_by_pl" {
		msg = "Completion returned to the officer."
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: msg}, true, nil
}
