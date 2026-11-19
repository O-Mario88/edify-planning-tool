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

// TestTheClosureQueueMatchesTheExistingPage files the work
// internal/closurepages/testdata/queue_golden.py filed (the first officer's
// work in each state the queue sorts into, called-off work with and without
// money paid out, and a closed visit), asks /activities/closure as each
// reader the golden asked, and compares the whole page. Skipped unless
// EDIFY_CLOSURE_QUEUE_GOLDEN names that file, written within the hour.
func TestTheClosureQueueMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_CLOSURE_QUEUE_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_CLOSURE_QUEUE_GOLDEN is not set")
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
	// The order queue_golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"activity", "activity_schedule_cost_line", "advance_request", "analytics_publish_record"}
	ctx := context.Background()
	clear := func() {
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'gclq%'`); err != nil {
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
	compareGolden(t, "/activities/closure", golden.Answers)
}
