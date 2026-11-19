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

// TestTheDailyDebriefMatchesTheExistingPage files the work and debriefs
// internal/debriefs/testdata/submit_golden.py filed (the first officer's
// work for today and an overdue visit, the first Lead's submitted debrief,
// the partner's draft, the Coordinator's returned one and the Admin's
// reviewed one), asks /debriefs/submit as each reader the golden asked, bare
// and carrying in an activity, and compares the whole page. Skipped unless
// EDIFY_DEBRIEF_SUBMIT_GOLDEN names that file, written within the hour.
func TestTheDailyDebriefMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_DEBRIEF_SUBMIT_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_DEBRIEF_SUBMIT_GOLDEN is not set")
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
	// The order submit_golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"activity", "daily_debrief", "daily_debrief_activity_link"}
	ctx := context.Background()
	clear := func() {
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'gdbf%'`); err != nil {
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
	compareGolden(t, "/debriefs/submit", golden.Answers)
}
