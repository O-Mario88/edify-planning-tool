//go:build integration

package integration

import (
	"encoding/json"
	"os"
	"testing"
)

// The existing feed's Country Map over the development seed: the map card
// with its totals line, and the country portfolio under it, for the Country
// Director on each filter and on the officer table's second page, and for
// every reader it opens for and refuses. Skipped unless
// EDIFY_COUNTRY_MAP_GOLDEN names a file
// internal/oversightportfolio/testdata/countrymap_golden.py wrote.
func TestCountryMapMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_COUNTRY_MAP_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_COUNTRY_MAP_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Answers []goldenAnswer `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing of the Country Map")
	}
	compareGolden(t, "/country-map/", golden.Answers)
}
