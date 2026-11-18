//go:build integration

package integration

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

// The profiles of many schools (a District's /districts/<id>, a
// Sub-region's /sub-regions/<id>), read by the existing page's own view
// and the feed's reader (internal/webpages/testdata/web_page.py), for the
// readers and queries they were asked with. Skipped unless
// EDIFY_SCOPE_PROFILES_GOLDEN names files (comma-separated) written within
// the hour.
func TestTheProfilesOfManySchoolsMatchTheExistingPages(t *testing.T) {
	paths := os.Getenv("EDIFY_SCOPE_PROFILES_GOLDEN")
	if paths == "" {
		t.Skip("EDIFY_SCOPE_PROFILES_GOLDEN is not set")
	}
	// Each file is one run of the oracle (its readers and queries).
	for _, path := range strings.Split(paths, ",") {
		compareScopeProfiles(t, path)
	}
}

func compareScopeProfiles(t *testing.T, path string) {
	t.Helper()
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
	// One comparison per profile asked.
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
