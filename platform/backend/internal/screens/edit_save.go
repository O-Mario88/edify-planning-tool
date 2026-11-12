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

// The app's Edit save through Go (docs/migration/31), behind
// EDIFY_GO_SAVES=edit_visit, exactly as the Cancel save (30.8): the
// existing application opens the drawer and composes the form its own save
// would post (DrawerFeedView, ?form_only=1, which saves nothing); Go makes
// the edit when it is 31.1's case, and answers in the words the existing
// feed gives. Anything else is forwarded unchanged, so an edit is never made
// by both.

// EditSaver is the Go edit (internal/activities.Service).
type EditSaver interface {
	Edit(ctx context.Context, p auth.Principal, req activities.EditRequest, origin activities.Origin) (activities.EditAnswer, error)
}

// WithEditSave makes the Edit drawer's saves Go's where Go takes them.
func (s *Service) WithEditSave(saver EditSaver, logger *slog.Logger) *Service {
	s.edits, s.logger = saver, logger
	return s
}

// The Edit drawer, and the view its form posts to.
var (
	editDrawer = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/edit-drawer$`)
	editSave   = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/edit$`)
)

// editInGo makes the edit in Go; served is false when the request is to be
// forwarded to the existing application as before.
func (s *Service) editInGo(
	ctx context.Context, message *screensv1.SaveDrawerRequest,
) (*screensv1.SaveDrawerResponse, bool, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	drawer := editDrawer.FindStringSubmatch(message.GetPath())
	if !ok || s.edits == nil || s.existingApp == nil || drawer == nil || principal.InActingAppointment {
		return nil, false, nil
	}
	var answer structpb.Struct
	if err := s.existingApp.Post(ctx, pathPageDrawer+"?form_only=1", message, &answer); err != nil {
		// The drawer's own refusal: the same the forwarded save meets.
		return nil, true, err
	}
	form, origin, ok := formOf(&answer)
	save := editSave.FindStringSubmatch(answer.GetFields()["save"].GetStringValue())
	if !ok || save == nil || save[1] != drawer[1] {
		return nil, false, nil
	}
	req, taken := activities.EditRequestFromForm(save[1], form)
	if !taken {
		return nil, false, nil
	}
	edited, err := s.edits.Edit(ctx, principal, req, origin)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		// error_fragment's words, read back as the feed reads them.
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(activities.EditErrorTitle + refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go edit failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(edited.Message) + " " + toastClose}, true, nil
}
