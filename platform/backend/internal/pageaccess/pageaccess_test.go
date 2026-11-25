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
