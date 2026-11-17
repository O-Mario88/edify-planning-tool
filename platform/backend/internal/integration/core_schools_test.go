//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreschools"
)

// coreSchoolsTables is what the golden files, parents first: the packages
// the page's own heal would make, found and cleared by their ids.
var coreSchoolsTables = []string{"activity", "core_plan", "core_school_profile", "core_activity_slot", "team_action"}

// The existing feed's Core Schools Planning, with its three lazily drawn
// tabs, for the CCEO who holds the core schools (this year and the one
// before, the pages and sizes, each filter and a search), a CCEO who holds
// none, the Programme Lead, the Accountant, IA and the Admin, and the
// partner login it refuses, and the Programme Lead's Team Core Oversight
// lens over a delivery chain on its first schools.
// Skipped unless EDIFY_CORE_SCHOOLS_GOLDEN names a file
// internal/coreschools/testdata/golden.py wrote within the hour.
func TestCoreSchoolsMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_CORE_SCHOOLS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_CORE_SCHOOLS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	idsOf := map[string][]string{}
	for _, table := range coreSchoolsTables {
		for _, row := range golden.Rows[table] {
			var r struct {
				ID string `json:"id"`
			}
			if err := json.Unmarshal(row, &r); err != nil {
				t.Fatal(err)
			}
			idsOf[table] = append(idsOf[table], r.ID)
		}
	}
	unfile := func() {
		for i := len(coreSchoolsTables) - 1; i >= 0; i-- {
			table := coreSchoolsTables[i]
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id::text = ANY($1)`, table), idsOf[table]); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	unfile()
	t.Cleanup(unfile)
	for _, table := range coreSchoolsTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	compareGolden(t, coreschools.Path, golden.Answers)
}
