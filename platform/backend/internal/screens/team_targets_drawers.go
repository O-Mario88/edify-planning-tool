package screens

// Team Targets' drawers (staff_views.team_targets_*_view), drawn by
// internal/teamtargets. They only read.

import (
	"context"
	"errors"
	"net/url"
	"strings"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teamtargets"
)

var teamTargetsDrawers = map[string]func(context.Context, schooldirectory.Querier, auth.Principal, map[string]string, time.Time) (*screensv1.PageDrawer, error){
	"/team-targets/sfid-backlog":       teamtargets.SFIDBacklog,
	"/team-targets/validation-backlog": teamtargets.ValidationBacklog,
	"/team-targets/matrix":             teamtargets.MatrixDrawer,
}

func (s *Service) teamTargetsDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	draw, ok := teamTargetsDrawers[strings.TrimSuffix(path, "/")]
	if !ok || s.db == nil {
		return nil, false, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This link is not valid.")
	}
	d, err := draw(ctx, s.db, p, teamtargets.Query(query), s.clock())
	var refused *teamtargets.RefusedError
	switch {
	case errors.As(err, &refused):
		return &screensv1.GetDrawerResponse{Refusal: refused.Message}, true, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}
