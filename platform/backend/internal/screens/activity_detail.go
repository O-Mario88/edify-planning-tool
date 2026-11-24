package screens

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

// An activity's detail drawer (/my-plan/<id>), the drawer every officer
// opens from Home, My Plan and the Calendar, in Go with Django absent.

// ActivityDetail draws it (internal/myplan.Service).
type ActivityDetail interface {
	DetailDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error)
}

// WithActivityDetail makes the drawer Go's with Django absent.
func (s *Service) WithActivityDetail(d ActivityDetail) *Service {
	s.activityDetail = d
	return s
}

func (s *Service) activityDetailInGo(ctx context.Context, p auth.Principal, pathOnly string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.activityDetail == nil || s.existingApp != nil {
		return nil, false, nil
	}
	id, ok := myplan.DetailID(strings.TrimSpace(pathOnly))
	if !ok {
		return nil, false, nil
	}
	d, err := s.activityDetail.DetailDrawer(ctx, p, id)
	switch {
	case errors.Is(err, myplan.ErrDetailHandOn):
		if s.logger != nil {
			// With Django absent the reader is told the drawer is not
			// available: say which part Go does not draw yet.
			s.logger.InfoContext(ctx, "the activity drawer is handed on", slog.String("activity", id), slog.String("reason", err.Error()))
		}
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}
