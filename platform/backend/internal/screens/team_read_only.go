package screens

import (
	"context"
	"errors"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

// My Plan's Reschedule and Cancel drawers with Django absent, where Go's
// own field forms (fieldFormInGo) have not drawn them: "Read only" for a
// reader who may open the work and not change it, else the existing
// drawer's form (internal/myplan.PlanDrawer).

// PlanDrawers draws them (internal/myplan.Service).
type PlanDrawers interface {
	PlanDrawer(ctx context.Context, p auth.Principal, id, kind string) (*screensv1.PageDrawer, error)
}

// WithPlanDrawers makes the two drawers Go's with Django absent.
func (s *Service) WithPlanDrawers(d PlanDrawers) *Service {
	s.planDrawers = d
	return s
}

func (s *Service) teamReadOnlyDrawer(ctx context.Context, p auth.Principal, pathOnly string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.existingApp != nil || s.planDrawers == nil {
		return nil, false, nil
	}
	m := planDrawerPath.FindStringSubmatch(strings.TrimSpace(pathOnly))
	if m == nil || (m[1] != "reschedule" && m[1] != "cancel") {
		return nil, false, nil
	}
	id := strings.Split(strings.TrimPrefix(pathOnly, "/my-plan/"), "/")[0]
	d, err := s.planDrawers.PlanDrawer(ctx, p, id, m[1])
	switch {
	case errors.Is(err, myplan.ErrDetailHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}
