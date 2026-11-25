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

// Piece 2: the Team Plan of a Programme Lead is drawn by Go, with work in
// the period or none; an advanced filter is handed on.
func TestPlanningOversightTeamPlanIsGosWhenTheTeamHasNothingPlanned(t *testing.T) {
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(lead, teamPlanningOversight, map[string]string{"fy": "2026", "district_id": "nowhere"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("an advanced filter: %v, want handed on", err)
	}
	busy, err := pageOf(lead, teamPlanningOversight, map[string]string{"fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("a team with FY 2026 work: %v", err)
	}
	// The tiles, the Whole team tab and the Field Plan fold the same work.
	total := busy.GetBlocks()[2].GetStrip().GetMetrics()[0].GetValue()
	tabs := busy.GetBlocks()[3].GetPanel().GetItems()[0].GetLinks().GetLinks()
	if tabs[0].GetText() != "Whole team" || tabs[0].GetCaption() != strings.ReplaceAll(total, ",", "") {
		t.Fatalf("Whole team tab %q, first tile %q", tabs[0].GetCaption(), total)
	}
	if got := busy.GetBlocks()[5].GetPanel().GetItems()[3].GetText(); got != tabs[0].GetCaption()+" planned" {
		t.Fatalf("field plan count = %q, want %s planned", got, tabs[0].GetCaption())
	}
	for _, b := range busy.GetBlocks() {
		if table := b.GetTable(); table != nil && table.GetPager() != nil && len(table.GetRows()) != 50 {
			t.Fatalf("a paged table shows %d rows, want 50", len(table.GetRows()))
		}
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

// Piece 3: a country reader's Team Plan is drawn by Go: a tab per
// Programme Lead, the tiles folding the chosen Lead's work (the first tab),
// the chosen Lead's officers as switches with only the open one's tables
// drawn. A lens the reader does not hold falls back to it, as the page does.
func TestPlanningOversightCountryLensIsGos(t *testing.T) {
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(director, teamPlanningOversight, map[string]string{"fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("the Country Director's Team Plan: %v", err)
	}
	var strip, leads, switches int
	var total string
	for i, b := range page.GetBlocks() {
		switch {
		case b.GetStrip() != nil:
			strip = i
			total = b.GetStrip().GetMetrics()[0].GetValue()
		case b.GetSegments() != nil:
			switches = i
			open := 0
			for _, s := range b.GetSegments().GetSegments() {
				if len(s.GetBlocks()) > 1 {
					open++
				}
			}
			if open > 1 {
				t.Fatalf("%d officer panels drawn, want at most one", open)
			}
		}
	}
	if got := page.GetBlocks()[strip].GetStrip().GetTitle(); got != "Country overview" {
		t.Fatalf("strip title %q", got)
	}
	tabs := page.GetBlocks()[strip+1].GetPanel().GetItems()[0].GetLinks().GetLinks()
	leads = len(tabs)
	if leads == 0 || tabs[0].GetCaption() != strings.ReplaceAll(total, ",", "") {
		t.Fatalf("%d Lead tabs, the first holding %s, the tile %q", leads, tabs[0].GetCaption(), total)
	}
	if switches == 0 {
		t.Fatal("no officer switches")
	}

	borrowAccount(t, "accountant@edify.org")
	accountant := sessionOf(t, "accountant@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(accountant, teamPlanningOversight, map[string]string{"view": "trainings"}); err != nil {
		t.Fatalf("a lens the Accountant does not hold: %v, want the Team Plan", err)
	}
}
