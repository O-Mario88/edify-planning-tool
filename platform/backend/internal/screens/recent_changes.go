package screens

import (
	"context"
	"errors"
	"regexp"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/recentchanges"
)

// The Planning page's Recent changes drawer (/planning/recent-changes), in Go
// with Django absent.

var recentChangesPath = regexp.MustCompile(`^/planning/recent-changes/?$`)

// RecentChanges reads the drawer (internal/recentchanges.Service).
type RecentChanges interface {
	Drawer(ctx context.Context, p auth.Principal) (*screensv1.PageDrawer, error)
}

// WithRecentChanges makes Recent changes Go's with Django absent.
func (s *Service) WithRecentChanges(r RecentChanges) *Service {
	s.recent = r
	return s
}

func (s *Service) recentChangesInGo(ctx context.Context, p auth.Principal, pathOnly string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.recent == nil || s.existingApp != nil || !recentChangesPath.MatchString(pathOnly) {
		return nil, false, nil
	}
	d, err := s.recent.Drawer(ctx, p)
	switch {
	case errors.Is(err, recentchanges.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}
