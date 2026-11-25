//go:build integration

package integration

import (
	"testing"

	"connectrpc.com/connect"
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
