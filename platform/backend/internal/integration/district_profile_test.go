//go:build integration

package integration

import (
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The District profile (/districts/<id>), read by the existing page's own
// view and the feed's reader (internal/webpages/testdata/web_page.py), for
// the readers and queries it was asked with. Skipped unless
// EDIFY_DISTRICT_PROFILE_GOLDEN names a file written within the hour.
func TestTheDistrictProfileMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_DISTRICT_PROFILE_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_DISTRICT_PROFILE_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time `json:"written"`
		Answers []struct {
			goldenAnswer
			Path string `json:"path"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	if len(golden.Answers) == 0 {
		t.Fatal("the golden has no answers")
	}
	// One comparison per district asked.
	byPath, order := map[string][]goldenAnswer{}, []string{}
	for _, a := range golden.Answers {
		if _, seen := byPath[a.Path]; !seen {
			order = append(order, a.Path)
		}
		byPath[a.Path] = append(byPath[a.Path], a.goldenAnswer)
	}
	for _, path := range order {
		compareGolden(t, path, byPath[path])
	}
}
