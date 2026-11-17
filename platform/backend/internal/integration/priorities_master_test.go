//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/prioritiesmaster"
)

// prioritiesMasterTables is what the golden files, parents first: the
// rows its transaction added, found and cleared by their ids.
var prioritiesMasterTables = []string{
	"hr_strategic_priority_cycle", "hr_milestone_metric_definition", "hr_strategic_priority", "hr_priority_milestone",
	"hr_milestone_target_component", "hr_milestone_activity_rule", "hr_milestone_allocation", "hr_milestone_period_target",
	"activity",
}

// The existing feed's Uganda Priorities for every kind of reader — the
// Programme Lead (team received and own share), a CCEO of the team and one
// outside it, the Project Coordinator (their own allocation), the RVP, the
// Regional Programme Lead and HR (the country's figures), the roles sent on
// to Target Distribution, and the Accountant it refuses — with no year
// asked, the Uganda master published and distributed, the master in draft,
// and the seed's own year (no master). Skipped unless
// EDIFY_PRIORITIES_MASTER_GOLDEN names a file
// internal/prioritiesmaster/testdata/golden.py wrote within the hour.
func TestPrioritiesMasterMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_PRIORITIES_MASTER_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PRIORITIES_MASTER_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []struct {
			goldenAnswer
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	idsOf := map[string][]string{}
	for _, table := range prioritiesMasterTables {
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
	clear := func() {
		for i := len(prioritiesMasterTables) - 1; i >= 0; i-- {
			table := prioritiesMasterTables[i]
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id::text = ANY($1)`, table), idsOf[table]); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	fileGoldenRows(t, ctx, prioritiesMasterTables, golden.Rows)
	served := []goldenAnswer{}
	for _, answer := range golden.Answers {
		served = append(served, answer.goldenAnswer)
	}
	compareGolden(t, prioritiesmaster.Path, served)
}
