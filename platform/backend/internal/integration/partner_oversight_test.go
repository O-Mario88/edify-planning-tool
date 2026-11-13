//go:build integration

package integration

import (
	"strings"
	"testing"

	"connectrpc.com/connect"
)

const partnerOversightPath = "/partner-oversight/"

// The gateway under test has no existing application behind it, so every
// answer here is Go's, and a reader Go passes on reads as unavailable.
func TestPartnerOversightAnOfficerWithNoPartnerWorkIsGos(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	page, err := pageOf(sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, nil)
	if err != nil {
		t.Fatalf("Partner Monitoring for cceo1: %v", err)
	}
	blocks := page.GetBlocks()
	if page.GetHeader().GetTitle() != "Partner Monitoring" || len(blocks) != 4 {
		t.Fatalf("got %q with %d blocks", page.GetHeader().GetTitle(), len(blocks))
	}
	tabs := blocks[1].GetLinkTabs().GetTabs()
	if len(tabs) != 1 || tabs[0].GetLabel() != "All team members 0" || !tabs[0].GetActive() {
		t.Errorf("team member tabs %v", tabs)
	}
	if note := blocks[2].GetStrip().GetMetrics()[0].GetNote(); note != "" {
		t.Errorf("an officer with no monitor has no Partner target, got %q", note)
	}
	if blocks[3].GetEmpty() == "" {
		t.Error("no empty state")
	}
}

func TestPartnerOversightALeadWithNoPartnerWorkSeesTheirTeamAndRegister(t *testing.T) {
	borrowAccount(t, "pl2@edify.org")
	page, err := pageOf(sessionOf(t, "pl2@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, map[string]string{"fy": "2028"})
	if err != nil {
		t.Fatalf("Partner Monitoring for pl2: %v", err)
	}
	blocks := page.GetBlocks()
	if len(blocks) != 7 {
		t.Fatalf("got %d blocks", len(blocks))
	}
	tabs := blocks[1].GetLinkTabs().GetTabs()
	if len(tabs) < 2 || tabs[1].GetLabel() != "Program Lead 2 0" || !strings.Contains(tabs[1].GetHref(), "&fy=2028&") {
		t.Errorf("team member tabs %v", tabs)
	}
	if note := blocks[2].GetStrip().GetMetrics()[0].GetNote(); !strings.Contains(note, "Partner target 0 visits") {
		t.Errorf("first tile note %q", note)
	}
	if got := blocks[5].GetStrip().GetMetrics(); len(got) != 4 || got[0].GetNote() != "FY2028 · meetings, orientations and follow-ups" {
		t.Errorf("register tiles %v", got)
	}
}

func TestPartnerOversightPassesOnPartnerWorkAndRefusesOthers(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	borrowAccount(t, "pl1@edify.org")
	borrowAccount(t, "business-transformation@edify.org")
	officer := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	// cceo1's completed FY 2026 Partner work is the existing application's.
	if _, err := pageOf(officer, partnerOversightPath, map[string]string{"fy": "2026"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Errorf("cceo1 in FY 2026: got %v, want the page passed on", err)
	}
	// A custom period from the export drawer is too.
	if _, err := pageOf(officer, partnerOversightPath, map[string]string{"period_type": "fy"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Errorf("custom period: got %v, want the page passed on", err)
	}
	if _, err := pageOf(sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, nil); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Errorf("pl1's team holds Partner work: got %v, want the page passed on", err)
	}
	if _, err := pageOf(sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Errorf("Business Transformation: got %v, want not found", err)
	}
}
