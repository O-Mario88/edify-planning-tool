package screens

import (
	"context"
	"net/url"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/programmerollout"
)

// The schools behind a Programme Rollout figure (/programme-rollout/schools),
// in Go with Django absent.

// RolloutDrawer draws it (internal/programmerollout.Service).
type RolloutDrawer interface {
	Drawer(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.PageDrawer, bool, error)
}

// WithRolloutDrawer makes the drawer Go's with Django absent.
func (s *Service) WithRolloutDrawer(r RolloutDrawer) *Service {
	s.rollout = r
	return s
}

func (s *Service) rolloutDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.rollout == nil || s.existingApp != nil {
		return nil, false, nil
	}
	parsed, err := url.Parse(rawPath)
	if err != nil || strings.TrimSuffix(parsed.Path, "/") != programmerollout.DrawerPath {
		return nil, false, nil
	}
	d, served, err := s.rollout.Drawer(ctx, p, parsed.Query())
	if !served || err != nil {
		return nil, served, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}
