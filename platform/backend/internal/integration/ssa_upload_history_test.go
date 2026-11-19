//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

// TestTheSSAUploadHistoryMatchesTheExistingPage files the batches and rows
// internal/iapages/testdata/upload_history_golden.py filed (fifty-five
// batches by three uploaders, each with ready, unmatched and refused rows),
// asks /ssa/upload/history/ as each reader the golden asked, with each
// filter and page, and compares the whole page. Skipped unless
// EDIFY_SSA_UPLOAD_HISTORY_GOLDEN names that file, written within the hour.
func TestTheSSAUploadHistoryMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_SSA_UPLOAD_HISTORY_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_SSA_UPLOAD_HISTORY_GOLDEN is not set")
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
	// The order upload_history_golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"ssa_import_batch", "ssa_import_row"}
	ctx := context.Background()
	clear := func() {
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'guph%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range tables {
		name := pgx.Identifier{table}.Sanitize()
		for _, row := range golden.Tables[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO `+name+` SELECT * FROM json_populate_record(NULL::`+name+`, $1::json)`, string(row)); err != nil {
				t.Fatalf("filing %s: %v", table, err)
			}
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/ssa/upload/history/", golden.Answers)
}
