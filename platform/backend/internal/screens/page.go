package screens

import (
	"context"
	"errors"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
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
	// When no existing application is configured (Django-absent cutover),
	// Go renders pages natively for desktop browsers too instead of handing
	// desktop readings or lazy-seed edge cases off to an absent upstream.
	ctx = pagegate.WithDesktop(ctx, message.GetDesktop() && s.existingApp != nil)
	ctx = pagegate.WithDjangoAbsent(ctx, s.existingApp == nil)
	if principal, ok := auth.PrincipalFrom(ctx); ok {
		effective := principal
		if principal.InActingAppointment {
			if principal.Acting == nil {
				return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
					"This page is not available to you.")
			}
			if acting.WithheldPage(principal.Acting.RoleKey, message.GetPath()) {
				return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
					"This page is withheld while acting in this capacity.")
			}
			if principal.Acting.ActingRole != "" {
				effective.ActiveRole = principal.Acting.ActingRole
			}
			if principal.Acting.ScopeType == acting.ScopePLTeam && principal.Acting.SeatStaffID != "" {
				effective.StaffProfileID = principal.Acting.SeatStaffID
			}
			effective.InActingAppointment = false
		}
		// A page whose reading is itself audited records who read it from
		// where (Employee Relations).
		ctx = origin.With(ctx, origin.Read(request.Peer().Addr, request.Header(), s.trustProxy, trace.FromContext(ctx).RequestID))
		for _, pages := range s.pages {
			response, served, err := pages.Build(ctx, effective, message.GetPath(), query)
			switch {
			case errors.Is(err, pagegate.ErrNotAvailable), errors.Is(err, schoolprofile.ErrNotFound):
				return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound,
					"This was not found, or it is not yours to view.")
			case errors.Is(err, pagegate.ErrForbidden):
				return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
					"This page is not available to you.")
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
	// The feed's own parameter (apps.mobile_feed.views.DESKTOP_PARAM); no
	// page query key can be it, as they start with a letter (queryKey).
	if message.GetDesktop() {
		full.Set("_desktop", "1")
	}
	return fetch[screensv1.GetPageResponse](ctx, s, pathPage+"?"+full.Encode())
}
