//go:build integration

package integration

import (
	"context"
	"net/http"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// Team Targets is Go's for a Programme Lead whose team has no agreed
// priorities yet: the filters, the team's progress strip and the empty
// matrix, at /team-targets and as Team Oversight's Target Performance lens
// (its tab active); a role without the page is told it is not available.
func TestTeamTargetsIsGos(t *testing.T) {
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(lead, "/team-targets", nil)
	if err != nil {
		t.Fatalf("Team Targets: %v", err)
	}
	blocks := page.GetBlocks()
	if page.GetHeader().GetTitle() != "Planning Oversight" || len(blocks) == 0 || blocks[0].GetFilters().GetFilters()[0].GetName() != "fy" {
		t.Fatalf("page %v", page)
	}
	strip := false
	for _, b := range blocks {
		if b.GetStrip().GetTitle() == "Team target progress" {
			strip = true
		}
	}
	if !strip {
		t.Fatalf("no team progress strip: %v", blocks)
	}
	lens, err := pageOf(lead, teamPlanningOversight, map[string]string{"view": "targets"})
	if err != nil {
		t.Fatalf("the Target Performance lens: %v", err)
	}
	tabs := lens.GetBlocks()[0].GetLinkTabs().GetTabs()
	if len(tabs) == 0 || !tabs[len(tabs)-1].GetActive() || tabs[len(tabs)-1].GetLabel() != "Target Performance" {
		t.Fatalf("lens tabs %v", tabs)
	}
	if len(lens.GetBlocks()) != len(blocks)+1 {
		t.Fatalf("the lens has %d blocks, the page %d", len(lens.GetBlocks()), len(blocks))
	}
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(cceo, "/team-targets", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a CCEO: %v, want not available", err)
	}
}

// With agreed targets the page draws the member matrix: one row a member,
// the month, quarters and year, and under each row their priorities by
// period (a past year, so no risk notice is due on the read).
func TestTeamTargetsDrawsTheMemberMatrix(t *testing.T) {
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM monthly_personal_target WHERE id LIKE 'gttm%'`); err != nil {
			t.Errorf("clearing the targets: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	if _, err := admin.Exec(ctx, `INSERT INTO monthly_personal_target (created_at, updated_at, id, user_id, fy, month_of_fy, target, area_id)
		SELECT now(), now(), 'gttm' || m, u.id, '2026', m, 3, a.id FROM "user" u, generate_series(1, 12) m, target_area a
		WHERE u.email = 'cceo@edify.org' AND a.key = 'school_visits'`); err != nil {
		t.Fatalf("setting the targets: %v", err)
	}
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(lead, "/team-targets", map[string]string{"fy": "2026", "month": "7"})
	if err != nil {
		t.Fatalf("Team Targets: %v", err)
	}
	for _, b := range page.GetBlocks() {
		table := b.GetTable()
		if len(table.GetColumns()) > 0 && table.GetColumns()[0].GetLabel() == "Team member" {
			if len(table.GetRows()) == 0 || len(table.GetRows()[0].GetDetailBlocks()) == 0 {
				t.Fatalf("matrix without member rows or their priorities: %v", table)
			}
			return
		}
	}
	t.Fatalf("no member matrix: %v", page.GetBlocks())
}

// The two backlog drawers behind the validation tiles are Go's: the team's
// work without an Activity SF ID and in each validation state; an unknown
// state and a role without the page are refused in the view's words.
func TestTeamTargetsBacklogDrawersAreGos(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	open := func(token, path string) *screensv1.GetDrawerResponse {
		t.Helper()
		answer, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, token))
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		return answer.Msg
	}
	if d := open(lead, "/team-targets/sfid-backlog?fy=2026").GetDrawer(); d.GetTitle() != "Activity SF ID backlog" || len(d.GetItems()) == 0 {
		t.Fatalf("SF ID backlog %v", d)
	}
	if d := open(lead, "/team-targets/validation-backlog?status=returned_by_ia&fy=2026").GetDrawer(); d.GetTitle() != "Returned by IA" {
		t.Fatalf("returned backlog %v", d)
	}
	if r := open(lead, "/team-targets/validation-backlog?status=other").GetRefusal(); r != "Unknown validation backlog." {
		t.Fatalf("an unknown state: %q", r)
	}
	if d := open(lead, "/team-targets/matrix?fy=2026&month=7").GetDrawer(); d.GetTitle() != "Team target matrix" || len(d.GetItems()) != 2 {
		t.Fatalf("the matrix %v", d)
	}
	if r := open(lead, "/team-targets/matrix?month=13").GetRefusal(); r != "Invalid month." {
		t.Fatalf("a month out of range: %q", r)
	}
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if r := open(cceo, "/team-targets/sfid-backlog").GetRefusal(); !strings.Contains(r, "Team Targets") {
		t.Fatalf("a CCEO: %q", r)
	}
}
