//go:build integration

package integration

import (
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
	// The Team Plan the Lead may open is the existing application's (piece 1
	// builds no lens).
	if _, err := pageOf(lead, teamPlanningOversight, nil); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("a Programme Lead opening Planning Oversight: %v, want handed on", err)
	}
}
