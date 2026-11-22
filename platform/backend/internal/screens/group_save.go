package screens

import (
	"context"
	"errors"
	"log/slog"
	"net/url"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/structpb"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The app's group Reschedule and group Cancel saves through Go (docs/
// migration/33), behind EDIFY_GO_SAVES=group_reschedule and group_cancel. As
// for the single saves (29.7, 30.8), the existing application opens the
// drawer the bar for ticked rows opens and composes the form its own save
// would post (DrawerFeedView, ?form_only=1, which saves nothing); Go makes the
// group when every ticked activity is one its single save takes, and answers
// in the words the existing feed gives (_saved_outcome reading the view's
// flash message, or its outcome partial when nothing changed). Anything else
// is forwarded whole, so a group is never split and no activity is saved by
// both.

// GroupMoveSaver is the Go group reschedule (internal/activities.Service).
type GroupMoveSaver interface {
	GroupReschedule(ctx context.Context, p auth.Principal, req activities.GroupRequest, origin activities.Origin) (activities.GroupAnswer, error)
}

// GroupCancelSaver is the Go group cancel (internal/activities.Service).
type GroupCancelSaver interface {
	GroupCancel(ctx context.Context, p auth.Principal, req activities.GroupRequest, origin activities.Origin) (activities.GroupAnswer, error)
}

// WithGroupMoveSave makes the group Reschedule drawer's saves Go's where Go
// takes them.
func (s *Service) WithGroupMoveSave(saver GroupMoveSaver, logger *slog.Logger) *Service {
	s.groupMoves, s.logger = saver, logger
	return s
}

// WithGroupCancelSave makes the group Cancel drawer's saves Go's where Go
// takes them.
func (s *Service) WithGroupCancelSave(saver GroupCancelSaver, logger *slog.Logger) *Service {
	s.groupCancels, s.logger = saver, logger
	return s
}

// The two drawers, which post to their own paths
// (activity_group_views.RESCHEDULE_PATH, CANCEL_PATH).
const (
	groupReschedulePath = "/activity-selection/reschedule"
	groupCancelPath     = "/activity-selection/cancel"
)

// groupInGo makes the group in Go; served is false when the request is to be
// forwarded to the existing application as before.
func (s *Service) groupInGo(
	ctx context.Context, message *screensv1.SaveDrawerRequest,
) (*screensv1.SaveDrawerResponse, bool, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	opened, err := url.Parse(message.GetPath())
	if !ok || err != nil || principal.InActingAppointment {
		return nil, false, nil
	}
	cancel := opened.Path == groupCancelPath
	switch {
	case opened.Path == groupReschedulePath && s.groupMoves != nil:
	case cancel && s.groupCancels != nil:
	default:
		return nil, false, nil
	}
	var form url.Values
	var origin activities.Origin
	if s.existingApp != nil {
		var answer structpb.Struct
		if err := s.existingApp.Post(ctx, pathPageDrawer+"?form_only=1", message, &answer); err != nil {
			// The drawer's own refusal: the same the forwarded save meets.
			return nil, true, err
		}
		var okForm bool
		form, origin, okForm = groupFormOf(&answer)
		if !okForm || answer.GetFields()["save"].GetStringValue() != opened.Path {
			return nil, false, nil
		}
	} else {
		form = directDrawerForm(message)
	}
	req := activities.GroupRequest{ActivityIDs: form["activity_ids"], Date: first(form["scheduled_date"]),
		Reason: first(form["reason"])}
	var done activities.GroupAnswer
	if cancel {
		done, err = s.groupCancels.GroupCancel(ctx, principal, req, origin)
	} else {
		done, err = s.groupMoves.GroupReschedule(ctx, principal, req, origin)
	}
	return groupOutcomeOf(ctx, s.logger, cancel, done, err)
}

func first(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return values[0]
}

// groupFormOf reads the form-only answer: each field a text, or a list of
// texts for a name the form repeats (one activity_ids per tick).
func groupFormOf(answer *structpb.Struct) (url.Values, activities.Origin, bool) {
	fields := answer.GetFields()
	posted := fields["form"].GetStructValue()
	if posted == nil {
		return nil, activities.Origin{}, false
	}
	form := url.Values{}
	for name, value := range posted.GetFields() {
		switch kind := value.GetKind().(type) {
		case *structpb.Value_StringValue:
			form.Add(name, kind.StringValue)
		case *structpb.Value_ListValue:
			for _, item := range kind.ListValue.GetValues() {
				text, ok := item.GetKind().(*structpb.Value_StringValue)
				if !ok {
					return nil, activities.Origin{}, false
				}
				form.Add(name, text.StringValue)
			}
		default:
			return nil, activities.Origin{}, false
		}
	}
	said := fields["origin"].GetStructValue().GetFields()
	return form, activities.Origin{
		IP:            said["ip"].GetStringValue(),
		UserAgent:     said["agent"].GetStringValue(),
		CorrelationID: said["correlation"].GetStringValue(),
	}, true
}

// groupOutcomeOf is the existing feed's answer for Go's group: the view's
// flash message when anything changed (_saved_outcome joins the success
// messages, unchanged), the outcome partial's words when nothing did, or
// error_fragment's words for a refusal of the group, each read back as the
// feed reads them.
func groupOutcomeOf(ctx context.Context, logger *slog.Logger, cancel bool, done activities.GroupAnswer, err error) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		words := refusal.Message
		if cancel {
			words = cancelErrorTitle + words
		}
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(words)}, true, nil
	case err != nil:
		if logger != nil {
			logger.ErrorContext(ctx, "the Go group failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	if len(done.Done) > 0 {
		return &screensv1.SaveDrawerResponse{Saved: true, Message: done.Message}, true, nil
	}
	return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(done.Outcome)}, true, nil
}
