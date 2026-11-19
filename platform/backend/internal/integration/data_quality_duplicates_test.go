//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestTheDuplicateReviewQueueMatchesTheExistingPage files the issues
// internal/dataquality/testdata/duplicates_golden.py filed (fifty-two open
// duplicate risks, one resolved, one of another kind), asks
// /data-quality/duplicates as each reader the golden asked, on each page,
// and compares the whole page. Skipped unless
// EDIFY_DATA_QUALITY_DUPLICATES_GOLDEN names that file, written within the
// hour.
func TestTheDuplicateReviewQueueMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_DATA_QUALITY_DUPLICATES_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_DATA_QUALITY_DUPLICATES_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM data_quality_issue WHERE id LIKE 'gdqd%'`); err != nil {
			t.Errorf("clearing the issues: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Tables["data_quality_issue"] {
		if _, err := admin.Exec(ctx, `INSERT INTO data_quality_issue SELECT * FROM json_populate_record(NULL::data_quality_issue, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing an issue: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/data-quality/duplicates", golden.Answers)
}
