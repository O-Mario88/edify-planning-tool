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

// TestTheGeographicalLocationSetupMatchesTheExistingPage files the rows
// internal/adminpanel/testdata/geography_golden.py filed (two districts, an
// approved and a draft Secondary District Group), asks
// /admin-panel/region-district-setup as each reader the golden asked, and
// compares the whole page. Skipped unless EDIFY_ADMIN_GEOGRAPHY_GOLDEN
// names that file, written within the hour.
func TestTheGeographicalLocationSetupMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_GEOGRAPHY_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_GEOGRAPHY_GOLDEN is not set")
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
	// The order geography_golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"district", "secondary_district_group", "secondary_district_group_member"}
	ctx := context.Background()
	clear := func() {
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'gdst%'`); err != nil {
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
	compareGolden(t, "/admin-panel/region-district-setup", golden.Answers)
}
