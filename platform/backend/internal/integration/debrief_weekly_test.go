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

// TestTheWeeklyDebriefReportMatchesTheExistingPage files the debriefs and
// reports internal/debriefs/testdata/weekly_golden.py filed (the first
// Lead's team debriefs over two weeks; the Lead's and the country's report
// for the earlier week, signed; their drafts for the last week), asks
// /debriefs/weekly-report as each reader the golden asked, for each week,
// and compares the whole page. A reader whose existing page writes a report
// as it opens is answered handed on. Skipped unless
// EDIFY_DEBRIEF_WEEKLY_GOLDEN names that file, written within the hour.
func TestTheWeeklyDebriefReportMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_DEBRIEF_WEEKLY_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_DEBRIEF_WEEKLY_GOLDEN is not set")
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
	// The order weekly_golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"daily_debrief", "weekly_debrief_report"}
	ctx := context.Background()
	clear := func() {
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'gdwr%'`); err != nil {
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
	compareGolden(t, "/debriefs/weekly-report", golden.Answers)
}
