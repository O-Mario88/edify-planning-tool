package todos

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The existing _country_budget_todos reads the budget of one hard-coded
// country ("Uganda") for every desk. Go reads the reader's own country and
// falls back to the configured one only for a reader with none (the Admin)
// (owner, 2026-11-13: "Can you fix those from the go side").
func TestTheBudgetDesksReadTheReadersOwnCountry(t *testing.T) {
	configured := rules.Admin.CountryBudget.Country
	cases := []struct {
		name, country, want string
	}{
		{"a Country Director of Kenya", "Kenya", "Kenya"},
		{"a reader of the configured country", configured, configured},
		{"a reader with no country (the Admin)", "", configured},
		{"spaces around the country", "  Kenya ", "Kenya"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := &reader{scope: schooldirectory.Scope{Country: c.country}}
			if got := budgetCountry(r); got != c.want {
				t.Fatalf("got %q, want %q", got, c.want)
			}
		})
	}
}
