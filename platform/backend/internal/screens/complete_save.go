package screens

import (
	"context"
	"errors"
	"log/slog"
	"regexp"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/structpb"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The app's Complete save through Go (docs/migration/183), behind
// EDIFY_GO_SAVES=complete_visit, exactly as the Cancel save (30): the
// existing application opens the drawer and composes the form its own save
// would post (DrawerFeedView, ?form_only=1, which saves nothing; the drawer
// itself starts a visit not yet begun as it opens, as the web's does); Go
// hands the visit in when it is 183.1's case, and answers in the words the
// existing feed gives. Anything else is forwarded unchanged, so a completion
// is never made by both.

// CompleteSaver is the Go completion (internal/activities.Service).
type CompleteSaver interface {
	Complete(ctx context.Context, p auth.Principal, req activities.CompleteRequest, origin activities.Origin) (activities.CompleteAnswer, error)
}

// WithCompleteSave makes the Complete drawer's saves Go's where Go takes them.
func (s *Service) WithCompleteSave(saver CompleteSaver, logger *slog.Logger) *Service {
	s.completions, s.logger = saver, logger
	return s
}

// The Complete drawer, and the view its form posts to.
var (
	completeDrawer = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/complete-drawer$`)
	completeSave   = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/complete$`)
)

// completeErrorTitle is the action error_fragment names before the words
// (my_plan_views.complete_activity_action: action="Submission Error").
const completeErrorTitle = "Submission Error: "

// completeInGo makes the completion in Go; served is false when the request
// is to be forwarded to the existing application as before.
func (s *Service) completeInGo(
	ctx context.Context, message *screensv1.SaveDrawerRequest,
) (*screensv1.SaveDrawerResponse, bool, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	drawer := completeDrawer.FindStringSubmatch(message.GetPath())
	if !ok || s.completions == nil || s.existingApp == nil || drawer == nil || principal.InActingAppointment {
		return nil, false, nil
	}
	var answer structpb.Struct
	if err := s.existingApp.Post(ctx, pathPageDrawer+"?form_only=1", message, &answer); err != nil {
		// The drawer's own refusal: the same the forwarded save meets.
		return nil, true, err
	}
	form, origin, ok := formOf(&answer)
	save := completeSave.FindStringSubmatch(answer.GetFields()["save"].GetStringValue())
	if !ok || save == nil || save[1] != drawer[1] {
		return nil, false, nil
	}
	completed, err := s.completions.Complete(ctx, principal, activities.CompleteRequest{
		ActivityID: save[1], Form: form,
	}, origin)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		if s.logger != nil {
			s.logger.InfoContext(ctx, "the completion is the existing application's", slog.String("why", err.Error()))
		}
		return nil, false, nil
	case errors.As(err, &refusal):
		// error_fragment's words, read back as the feed reads them.
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(completeErrorTitle + refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go completion failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(completed.Message) + " " + toastClose}, true, nil
}
