package pageaccess

import (
	_ "embed"
	"encoding/json"
	"testing"
)

//go:embed cases_test.json
var casesJSON []byte

// The cases are can_open_url's own answers, printed by the existing
// application for each role and link.
func TestCanOpenIsTheExistingAnswer(t *testing.T) {
	var cases []struct {
		Role string `json:"role"`
		URL  string `json:"url"`
		Open bool   `json:"open"`
	}
	if err := json.Unmarshal(casesJSON, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		if got := CanOpen(c.Role, false, c.URL); got != c.Open {
			t.Errorf("%s opening %q: got %v, want %v", c.Role, c.URL, got, c.Open)
		}
	}
}

func TestEveryExistingRouteCompiles(t *testing.T) {
	if len(routes) < 1000 {
		t.Fatalf("only %d routes read", len(routes))
	}
}

// The gate's refusal names the view's pages for a role that holds none of
// them, and nothing for a role it lets in or a path no gate covers.
func TestRefusedPagesNamesTheGatesPages(t *testing.T) {
	if got := RefusedPages("HumanResources", false, "/partner-oversight/detail?assignment_id=x"); len(got) != 1 || got[0] != "partner_oversight" {
		t.Fatalf("HR on Partner Oversight: %v", got)
	}
	if got := RefusedPages("Program Lead", false, "/partner-oversight/detail"); got != nil {
		t.Fatalf("a Lead on Partner Oversight: %v", got)
	}
	// A download names its page too, so the export refused is audited.
	if got := RefusedPages("Program Lead", false, "/ia/impact-report/download"); len(got) != 1 || got[0] != "ia_dashboard" {
		t.Fatalf("a Lead on the live evidence annex: %v", got)
	}
	if got := RefusedPages("ImpactAssessment", false, "/ia/impact-report/download"); got != nil {
		t.Fatalf("IA on the live evidence annex: %v", got)
	}
	if got := RefusedPages("HumanResources", false, "/no-such-page-at-all"); got != nil {
		t.Fatalf("an unknown path: %v", got)
	}
}
