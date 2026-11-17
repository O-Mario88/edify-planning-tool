//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"
)

// iaDashboardTables is what the golden files, parents first.
var iaDashboardTables = []string{"activity", "ssa_record", "project_school_assignment", "upload_batch", "unmatched_ssa_record", "ia_duplicate_activity", "evidence_record"}

// The existing feed's Impact Assessment dashboard on its Outcomes (each
// year, a project cohort), Today and Operations views, over verification
// work the seed lacks (waiting, overdue, cluster-wide and never-stamped
// work, work the queue leaves out, returned work, a duplicate, evidence, a
// pending SSA, an unmatched row and a failed upload) and project enrolments
// measured, under review and awaiting their follow-up, for the readers the
// page opens for and those it refuses. Collection, Impact reports and Map
// stay with the existing application. The ages move with
// the clock, so the answers hold for half an hour. Skipped unless
// EDIFY_IA_DASHBOARD_GOLDEN names a file internal/iapages/testdata/
// dashboard_golden.py wrote within the half hour.
func TestTheIADashboardMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_IA_DASHBOARD_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_IA_DASHBOARD_GOLDEN is not set")
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
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden answers were written at %s; their ages have moved", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(iaDashboardTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gid%%'`, iaDashboardTables[i])); err != nil {
				t.Errorf("clearing %s: %v", iaDashboardTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range iaDashboardTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing of the dashboard")
	}
	compareGolden(t, "/ia/dashboard/", golden.Answers)
}
