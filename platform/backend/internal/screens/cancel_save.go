package screens

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"regexp"
	"strings"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/structpb"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The app's Cancel save through Go (docs/migration/30), behind
// EDIFY_GO_SAVES=cancel_visit, exactly as the Reschedule save (29.7): the
// existing application opens the drawer and composes the form its own save
// would post (DrawerFeedView, ?form_only=1, which saves nothing); Go calls
// the visit off when it is 30.1's case, and answers in the words the
// existing feed gives. Anything else is forwarded unchanged, so a cancel is
// never made by both.

// CancelSaver is the Go cancel (internal/activities.Service).
type CancelSaver interface {
	Cancel(ctx context.Context, p auth.Principal, req activities.CancelRequest, origin activities.Origin) (activities.CancelAnswer, error)
}

// WithCancelSave makes the Cancel drawer's saves Go's where Go takes them.
func (s *Service) WithCancelSave(saver CancelSaver, logger *slog.Logger) *Service {
	s.cancels, s.logger = saver, logger
	return s
}

// The Cancel drawer, and the view its form posts to.
var (
	cancelDrawer = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/cancel-drawer$`)
	cancelSave   = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/cancel$`)
)

// cancelInGo makes the cancel in Go; served is false when the request is to
// be forwarded to the existing application as before.
func (s *Service) cancelInGo(
	ctx context.Context, message *screensv1.SaveDrawerRequest,
) (*screensv1.SaveDrawerResponse, bool, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	drawer := cancelDrawer.FindStringSubmatch(message.GetPath())
	if !ok || s.cancels == nil || drawer == nil || principal.InActingAppointment {
		return nil, false, nil
	}
	var form url.Values
	var origin activities.Origin
	activityID := drawer[1]
	if s.existingApp != nil {
		var answer structpb.Struct
		if err := s.existingApp.Post(ctx, pathPageDrawer+"?form_only=1", message, &answer); err != nil {
			// The drawer's own refusal: the same the forwarded save meets.
			return nil, true, err
		}
		var okForm bool
		form, origin, okForm = formOf(&answer)
		save := cancelSave.FindStringSubmatch(answer.GetFields()["save"].GetStringValue())
		if !okForm || save == nil || save[1] != drawer[1] {
			return nil, false, nil
		}
		activityID = save[1]
	} else {
		form = directDrawerForm(message)
	}
	cancelled, err := s.cancels.Cancel(ctx, principal, activities.CancelRequest{
		ActivityID: activityID, Reason: strings.TrimSpace(form.Get("reason")), Sessions: s.existingApp == nil,
	}, origin)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		// error_fragment's words, read back as the feed reads them.
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(cancelErrorTitle + refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go cancel failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(cancelled.Message) + " " + toastClose}, true, nil
}

// cancelErrorTitle is the action error_fragment names before the words
// (my_plan_views.cancel_activity_action: action="Cancellation Error").
const cancelErrorTitle = "Cancellation Error: "
