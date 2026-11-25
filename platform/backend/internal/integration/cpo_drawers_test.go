//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// Country Planning Oversight's drawers are Go's: a card opened, a Lead (the
// Director's only form, the team asks; Impact Assessment's full figures),
// and an empty follow-up register; a role without the page is refused.
func TestCountryOversightDrawersAreGos(t *testing.T) {
	ctx := context.Background()
	var lead string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'pl1@edify.org'`).
		Scan(&lead); err != nil {
		t.Fatalf("the Lead: %v", err)
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
	card := open(director, "/country-planning-oversight/drawer?kind=kpi&metric=cpo_staff_visit_planning").GetDrawer()
	if card.GetTitle() != "Staff Visit Planning" || len(card.GetItems()) < 4 || card.GetCanSubmit() {
		t.Fatalf("the card: %v", card)
	}
	asks := open(director, "/country-planning-oversight/drawer?kind=lead&key="+lead).GetDrawer()
	if len(asks.GetItems()) != 1 || asks.GetItems()[0].GetField().GetName() != "issue" || asks.GetSubmitLabel() != "Send" {
		t.Fatalf("the Director's Lead drawer: %v", asks)
	}
	if fu := open(director, "/country-planning-oversight/drawer?kind=followups&show=all&fy=2001").GetDrawer(); fu.GetTitle() != "Follow-ups" ||
		fu.GetItems()[0].GetText() != "No follow-up has been sent this year." {
		t.Fatalf("an empty register: %v", fu)
	}
	borrowAccount(t, "ia@edify.org")
	ia := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	full := open(ia, "/country-planning-oversight/drawer?kind=lead&key="+lead).GetDrawer()
	if len(full.GetItems()) < 5 || full.GetItems()[0].GetHeading() != "Figures" {
		t.Fatalf("Impact Assessment's Lead drawer: %v", full)
	}
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	if r := open(hr, "/country-planning-oversight/drawer?kind=kpi&metric=cpo_staff_visit_planning").GetRefusal(); r != "Access Denied: Your active role does not have permission to view Country Planning Oversight." {
		t.Fatalf("HR: %q", r)
	}
}
