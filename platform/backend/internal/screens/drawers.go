package screens

import (
	"context"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// The profile's drawers, read and saved by the existing application's own
// drawer views (apps.mobile_feed SchoolDrawerFeedView). The feed decides
// which drawers exist; the gateway only refuses a name that is not a plain
// word, so nothing else of the existing application can be reached.

const pathDrawerOptions = "/api/mobile/v1/drawers/options"

var (
	drawerKind   = regexp.MustCompile(`^[a-z][a-z-]{0,31}$`)
	fieldName    = regexp.MustCompile(`^[a-z][a-z0-9_]{0,63}$`)
	optionSource = regexp.MustCompile(`^/[a-z0-9/-]{1,63}$`)
)

func requireDrawer(ctx context.Context, schoolID, kind string) error {
	if err := requireSchool(ctx, schoolID); err != nil {
		return err
	}
	if !drawerKind.MatchString(kind) {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This drawer does not exist.")
	}
	return nil
}

// GetSchoolDrawer returns one of a school's drawers as the web draws it.
func (s *Service) GetSchoolDrawer(
	ctx context.Context, request *connect.Request[screensv1.GetSchoolDrawerRequest],
) (*connect.Response[screensv1.GetSchoolDrawerResponse], error) {
	message := request.Msg
	if err := requireDrawer(ctx, message.GetSchoolId(), message.GetKind()); err != nil {
		return nil, err
	}
	return fetch[screensv1.GetSchoolDrawerResponse](ctx, s, schoolPath(message.GetSchoolId(), "drawers/"+message.GetKind()))
}

// SaveSchoolDrawer saves a drawer through the web view that saves it.
func (s *Service) SaveSchoolDrawer(
	ctx context.Context, request *connect.Request[screensv1.SaveSchoolDrawerRequest],
) (*connect.Response[screensv1.SaveSchoolDrawerResponse], error) {
	message := request.Msg
	if err := requireDrawer(ctx, message.GetSchoolId(), message.GetKind()); err != nil {
		return nil, err
	}
	return send[screensv1.SaveSchoolDrawerResponse](ctx, s, schoolPath(message.GetSchoolId(), "drawers/"+message.GetKind()), message)
}

// GetDrawerOptions returns the choices a field reloads when another changes.
func (s *Service) GetDrawerOptions(
	ctx context.Context, request *connect.Request[screensv1.GetDrawerOptionsRequest],
) (*connect.Response[screensv1.GetDrawerOptionsResponse], error) {
	message := request.Msg
	if !optionSource.MatchString(message.GetSource()) || !fieldName.MatchString(message.GetName()) ||
		message.GetName() == "source" || len(message.GetValue()) > maxSchoolIDLength {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "These choices do not exist.")
	}
	query := url.Values{"source": {message.GetSource()}, message.GetName(): {message.GetValue()}}
	return fetch[screensv1.GetDrawerOptionsResponse](ctx, s, pathDrawerOptions+"?"+query.Encode())
}
