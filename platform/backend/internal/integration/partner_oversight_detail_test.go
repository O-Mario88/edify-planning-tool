//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// Partner Oversight's hand-over drawer is Go's: for the Director (no forms)
// the whole record from its next action to its verification; a hand-over
// that is not there is "Not available"; a role without the page is refused.
func TestPartnerOversightDetailIsGos(t *testing.T) {
	ctx := context.Background()
	var id string
	if err := admin.QueryRow(ctx, `SELECT pa.id FROM partner_assignment pa WHERE pa.scheduled_activity_id IS NOT NULL
  AND (pa.project_id IS NULL OR COALESCE(pa.focus_intervention, '') <> '') ORDER BY pa.id LIMIT 1`).Scan(&id); err != nil {
		t.Fatalf("a hand-over: %v", err)
	}
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	open := func(token, path string) *screensv1.GetDrawerResponse {
		t.Helper()
		answer, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, token))
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		return answer.Msg
	}
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	d := open(director, "/partner-oversight/detail?assignment_id="+id).GetDrawer()
	headings := []string{}
	for _, it := range d.GetItems() {
		if h := it.GetHeading(); h != "" {
			headings = append(headings, h)
		}
	}
	if len(headings) < 5 || headings[0] != "Next action" || headings[len(headings)-1] != "Delivery & verification" || d.GetCanSubmit() {
		t.Fatalf("the hand-over %v", d)
	}
	if nope := open(director, "/partner-oversight/detail?assignment_id=nowhere").GetDrawer(); nope.GetTitle() != "Not available" {
		t.Fatalf("a hand-over that is not there: %v", nope)
	}
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	if r := open(hr, "/partner-oversight/detail?assignment_id="+id).GetRefusal(); r != "Access Denied: Your active role does not have permission to view Partner Oversight." {
		t.Fatalf("HR: %q", r)
	}
}
