package screens

import (
	"context"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

// teamReadOnlyMessage is scoping.TEAM_READ_ONLY_MESSAGE.
const teamReadOnlyMessage = "You can see this activity but not change it: a team member's scheduled work is edited, rescheduled or cancelled by the person responsible for it."

// teamReadOnlyDrawer is the Reschedule and Cancel drawers' first answer
// (my_plan_views._team_read_only): a reader who may open the activity and
// may not run it reads "Read only". Everyone else is the existing view's.
func (s *Service) teamReadOnlyDrawer(ctx context.Context, p auth.Principal, pathOnly string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.existingApp != nil || s.db == nil {
		return nil, false, nil
	}
	m := planDrawerPath.FindStringSubmatch(strings.TrimSpace(pathOnly))
	if m == nil {
		return nil, false, nil
	}
	id := strings.Split(strings.TrimPrefix(pathOnly, "/my-plan/"), "/")[0]
	access, err := myplan.ReadActivityAccess(ctx, s.db, p, id, s.clock())
	if err != nil {
		return nil, true, err
	}
	if !access.Decided || !access.Found || !access.Visible || access.Runnable {
		return nil, false, nil
	}
	return &screensv1.GetDrawerResponse{Drawer: &screensv1.PageDrawer{
		Title: "Read only", HasRequired: true, CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: teamReadOnlyMessage, Tone: "info"}}}},
	}}, true, nil
}
