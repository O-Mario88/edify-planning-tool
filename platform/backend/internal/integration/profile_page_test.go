//go:build integration

package integration

import (
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestProfilePageMatchesTheExistingPage compares Go's /profile builder against
// the golden produced by webpages/testdata/web_page.py. Skipped unless
// EDIFY_PROFILE_GOLDEN names that file, written within the hour.
func TestProfilePageMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_PROFILE_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PROFILE_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time      `json:"written"`
		Answers []goldenAnswer `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/profile", golden.Answers)
}
