//go:build integration

package integration

import (
	"strings"
	"testing"

	"connectrpc.com/connect"
)

const (
	teamPlanningOversight    = "/team-planning-oversight/"
	countryPlanningOversight = "/country-planning-oversight/"
)

// The gateway under test has no existing application behind it, so a page
// Go hands on is "not available here yet" (Unavailable), and a page Go
// refuses is the feed's "not available" (NotFound).
func TestPlanningOversightRefusesTheReadersItsGatesRefuse(t *testing.T) {
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	for _, path := range []string{teamPlanningOversight, countryPlanningOversight} {
		for _, query := range []map[string]string{nil, {"view": "trainings"}, {"view": "execution"}} {
			if _, err := pageOf(cceo, path, query); connect.CodeOf(err) != connect.CodeNotFound {
				t.Fatalf("a CCEO opening %s %v: %v, want not found", path, query, err)
			}
		}
	}

	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(lead, countryPlanningOversight, nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Programme Lead opening Country Oversight: %v, want not found", err)
	}
	if _, err := pageOf(lead, teamPlanningOversight, map[string]string{"format": "xml"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a format the feed cannot render: %v, want not found", err)
	}
	// A lens Go does not draw is the existing application's.
	if _, err := pageOf(lead, teamPlanningOversight, map[string]string{"view": "targets"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("a Programme Lead opening Target Performance: %v, want handed on", err)
	}
}

// Piece 2: the Team Plan of a Programme Lead whose team has work in the
// period is handed on; one with none is drawn by Go.
func TestPlanningOversightTeamPlanIsGosWhenTheTeamHasNothingPlanned(t *testing.T) {
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(lead, teamPlanningOversight, map[string]string{"fy": "2026", "period": "fy"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("a team with FY 2026 work: %v, want handed on", err)
	}
	page, err := pageOf(lead, teamPlanningOversight, map[string]string{"fy": "2025", "owner": "mine"})
	if err != nil {
		t.Fatalf("a team with nothing in FY 2025: %v", err)
	}
	if got := page.GetHeader().GetTitle(); got != "Planning Oversight" {
		t.Fatalf("title = %q", got)
	}
	blocks := page.GetBlocks()
	if len(blocks) != 17 {
		t.Fatalf("%d blocks, want 17", len(blocks))
	}
	if got := blocks[0].GetLinkTabs().GetTabs()[0].GetLabel(); got != "Team Plan" {
		t.Fatalf("first lens = %q", got)
	}
	if got := blocks[4].GetSection(); got != "My Work" {
		t.Fatalf("section = %q, want My Work", got)
	}
	if got := blocks[5].GetPanel().GetItems()[1].GetHeading(); !strings.HasSuffix(got, " Field Plan FY 2025") {
		t.Fatalf("field plan heading = %q", got)
	}
	links := blocks[3].GetPanel().GetItems()[0].GetLinks().GetLinks()
	if links[0].GetText() != "Whole team" || links[1].GetText() != "My Work" || links[0].GetCaption() != "0" {
		t.Fatalf("owner tabs = %v", links[:2])
	}
	if got := blocks[2].GetStrip().GetMetrics()[0].GetValue(); got != "0" {
		t.Fatalf("first tile = %q", got)
	}
	if got := blocks[16].GetPanel().GetTitle(); got != "Flagged schools" {
		t.Fatalf("last panel = %q", got)
	}
}
