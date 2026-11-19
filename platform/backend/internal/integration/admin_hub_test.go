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

// TestTheAdminDashboardMatchesTheExistingPage files the rows
// internal/adminpanel/testdata/hub_golden.py filed (a school whose owner is
// unmatched, a costed visit with no cost lines and an online training that
// needs none), asks /admin-panel as each reader the golden asked, and
// compares the whole page, both alerts raised. Skipped unless
// EDIFY_ADMIN_HUB_GOLDEN names that file, written within the hour.
func TestTheAdminDashboardMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_HUB_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_HUB_GOLDEN is not set")
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
	// The order hub_golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"school", "activity"}
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM data_quality_issue WHERE school_id LIKE 'gadm%'`); err != nil {
			t.Errorf("clearing the school's issues: %v", err)
		}
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'gadm%'`); err != nil {
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
	compareGolden(t, "/admin-panel", golden.Answers)
}
