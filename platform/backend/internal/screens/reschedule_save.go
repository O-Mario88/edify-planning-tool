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

// The app's Reschedule save through Go (docs/migration/29), behind
// EDIFY_GO_SAVES=reschedule_visit. As for the Schedule save (27 §27.10), the
// existing application opens the drawer and composes the form its own save
// would post (DrawerFeedView, ?form_only=1, which saves nothing); Go makes
// the move when it is 29.1's case, and answers in the words the existing
// feed gives (_saved_outcome). Anything else is forwarded unchanged, so a
// move is never made by both.

// MoveSaver is the Go move (internal/activities.Service).
type MoveSaver interface {
	Reschedule(ctx context.Context, p auth.Principal, req activities.MoveRequest, origin activities.Origin) (activities.MoveAnswer, error)
}

// WithMoveSave makes the Reschedule drawer's saves Go's where Go takes them.
func (s *Service) WithMoveSave(saver MoveSaver, logger *slog.Logger) *Service {
	s.moves, s.logger = saver, logger
	return s
}

// The Reschedule drawer, and the view its form posts to.
var (
	rescheduleDrawer = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/reschedule-drawer$`)
	rescheduleSave   = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/reschedule$`)
)

// toastClose is the saved toast's close button (partials/planning/
// saved_toast.html), which the feed reads as the toast's last word.
const toastClose = "×"

// rescheduleInGo makes the move in Go; served is false when the request is
// to be forwarded to the existing application as before.
func (s *Service) rescheduleInGo(
	ctx context.Context, message *screensv1.SaveDrawerRequest,
) (*screensv1.SaveDrawerResponse, bool, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	drawer := rescheduleDrawer.FindStringSubmatch(message.GetPath())
	if !ok || s.moves == nil || s.existingApp == nil || drawer == nil || principal.InActingAppointment {
		return nil, false, nil
	}
	var answer structpb.Struct
	if err := s.existingApp.Post(ctx, pathPageDrawer+"?form_only=1", message, &answer); err != nil {
		// The drawer's own refusal: the same the forwarded save meets.
		return nil, true, err
	}
	form, origin, ok := formOf(&answer)
	save := rescheduleSave.FindStringSubmatch(answer.GetFields()["save"].GetStringValue())
	if !ok || save == nil || save[1] != drawer[1] {
		return nil, false, nil
	}
	moved, err := s.moves.Reschedule(ctx, principal, activities.MoveRequest{
		ActivityID: save[1], Date: form.Get("scheduled_date"), Reason: form.Get("reason"),
	}, origin)
	return moveOutcomeOf(ctx, s.logger, moved, err)
}

// moveOutcomeOf is the existing feed's answer for Go's move: saved_in_place's
// toast, or error_fragment's words, each read back as the feed reads them.
func moveOutcomeOf(ctx context.Context, logger *slog.Logger, moved activities.MoveAnswer, err error) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if logger != nil {
			logger.ErrorContext(ctx, "the Go move failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(moved.Message) + " " + toastClose}, true, nil
}
