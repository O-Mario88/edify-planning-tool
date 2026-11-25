package screens

// Team Oversight's record drawer (oversight_views.oversight_detail_view),
// drawn by internal/planningoversight. It only reads; one Go cannot draw yet
// is handed on.

import (
	"context"
	"errors"
	"net/url"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningoversight"
)

func (s *Service) teamOversightDetailInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	if strings.TrimSuffix(path, "/") != planningoversight.DetailPath || s.db == nil {
		return nil, false, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This link is not valid.")
	}
	d, refusal, err := planningoversight.NewService(s.db, s.clock).Detail(ctx, p, query)
	switch {
	case errors.Is(err, planningoversight.ErrDetailHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	case refusal != "":
		return &screensv1.GetDrawerResponse{Refusal: refusal}, true, nil
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}
