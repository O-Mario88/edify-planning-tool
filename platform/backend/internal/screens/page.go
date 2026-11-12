package screens

import (
	"context"
	"errors"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// Any page the app draws from its components, read by the existing
// application's own view (apps.mobile_feed PageFeedView). The feed names the
// pages that are reachable and applies the page's own gate; the gateway only
// refuses a path or a query that is not plain.

const pathPage = "/api/mobile/v1/page"

// pagePath is a web path of plain segments: "/todos", "/clusters/c1".
var pagePath = regexp.MustCompile(`^(/[a-z0-9][a-z0-9_-]{0,63}){1,4}/?$`)

// GetPage returns a page as the web draws it for the reader.
func (s *Service) GetPage(
	ctx context.Context, request *connect.Request[screensv1.GetPageRequest],
) (*connect.Response[screensv1.GetPageResponse], error) {
	message := request.Msg
	if !pagePath.MatchString(message.GetPath()) {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This page cannot be opened.")
	}
	query, err := pageQuery(ctx, message.GetQuery())
	if err != nil {
		return nil, err
	}
	if query.Has("path") {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This page cannot be opened.")
	}
	if principal, ok := auth.PrincipalFrom(ctx); ok && !principal.InActingAppointment {
		for _, pages := range s.pages {
			response, served, err := pages.Build(ctx, principal, message.GetPath(), query)
			switch {
			case errors.Is(err, pagegate.ErrNotAvailable):
				return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound,
					"This was not found, or it is not yours to view.")
			case err != nil:
				return nil, apierr.Internal(ctx, s.logger, err)
			case served:
				return connect.NewResponse(response), nil
			}
		}
	}
	full := url.Values{"path": {message.GetPath()}}
	for key, values := range query {
		full[key] = values
	}
	return fetch[screensv1.GetPageResponse](ctx, s, pathPage+"?"+full.Encode())
}
