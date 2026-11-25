//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// My Plan's Export options form opens from Go for a role with My Plan, and
// is refused in the page gate's words to one without it.
func TestMyPlanExportFormIsGos(t *testing.T) {
	ctx := context.Background()
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	got, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: "/my-plan/export-drawer"}, cceo))
	if err != nil || got.Msg.GetDrawer().GetTitle() != "Export My Plan" || got.Msg.GetDrawer().GetSubmitLabel() != "Download Excel" {
		t.Fatalf("the form: %v %v", got, err)
	}
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: "/my-plan/export-drawer"}, hr)); err != nil ||
		r.Msg.GetRefusal() != "Access Denied: Your active role does not have permission to view My Plan." {
		t.Fatalf("HR: %v %v", r, err)
	}
}
