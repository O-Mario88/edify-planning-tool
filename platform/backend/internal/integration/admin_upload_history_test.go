//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestTheSchoolUploadHistoryMatchesTheExistingPage files the batches
// internal/adminpanel/testdata/upload_history_golden.py filed (fifty-two
// batches by four uploaders in every status), asks
// /admin-panel/school-upload-history as each reader the golden asked, and
// compares the whole page. Skipped unless EDIFY_ADMIN_UPLOAD_HISTORY_GOLDEN
// names that file, written within the hour.
func TestTheSchoolUploadHistoryMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_UPLOAD_HISTORY_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_UPLOAD_HISTORY_GOLDEN is not set")
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
		if _, err := admin.Exec(ctx, `DELETE FROM upload_batch WHERE id LIKE 'gaup%'`); err != nil {
			t.Errorf("clearing the batches: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Tables["upload_batch"] {
		if _, err := admin.Exec(ctx, `INSERT INTO upload_batch SELECT * FROM json_populate_record(NULL::upload_batch, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a batch: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/admin-panel/school-upload-history", golden.Answers)
}
